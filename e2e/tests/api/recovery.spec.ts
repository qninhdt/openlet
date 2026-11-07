import { randomUUID } from 'node:crypto';
import { test, expect, directory, objectFile, inline } from '../../fixtures/api-test.ts';
import { lockFilesystemRoot } from '../../fixtures/filesystem-lock.ts';
import { recoveryGuide } from '../../fixtures/documents.ts';
import { restartService } from '../../fixtures/restart-service.ts';
import { setTemporalRunning, temporalIsHealthy, triggerStorageMaintenance, recordLifecycleHistories, recordWorkflowHistory, filesystemDeletionIsRunning, terminateWorkspaceDeletion } from '../../fixtures/temporal-control.ts';

test('copy and purge complete while Temporal is unavailable', async ({ session }) => {
  const base = `/v1/filesystems/${session.filesystemId}/scopes/${session.scopeId}`;
  const source = await inline(session, 'source.bin', Buffer.from('copy'));
  const options = { headers: { 'idempotency-key': randomUUID(), 'if-match': '"1"' }, data: { parent_id: session.rootId, name: 'copied.bin' } };
  await setTemporalRunning(false);
  try {
    const response = await session.api.post(`${base}/nodes/${source.id}:copy`, options);
    expect(response.status()).toBe(201);
    const copied = await response.json();
    expect(await (await session.api.get(`${base}/nodes/${copied.id}/content`)).body()).toEqual(Buffer.from('copy'));
    const repeated = await session.api.post(`${base}/nodes/${source.id}:copy`, options);
    expect(repeated.status()).toBe(201);
    expect((await repeated.json()).id).toBe(copied.id);
    const trashed = await session.api.delete(`${base}/nodes/${copied.id}`, { headers: { 'if-match': response.headers().etag } });
    expect(trashed.status()).toBe(201);
    const entry = await trashed.json();
    expect((await session.api.delete(`${base}/trash-entries/${entry.id}`)).status()).toBe(204);
    expect((await (await session.api.get(`/v1/filesystems/${session.filesystemId}`)).json()).used_bytes).toBe('4');
  } finally { await setTemporalRunning(true); }
  await expect.poll(temporalIsHealthy).toBe(true);
});

test('source changes during direct copy return an error and retain committed output', async ({ session, controls, playwright }) => {
  const base = `/v1/filesystems/${session.filesystemId}/scopes/${session.scopeId}`;
  const folder = await directory(session, 'changing-source');
  const storage = await playwright.request.newContext();
  try {
    const file = await objectFile(session, storage, 'source.bin', Buffer.alloc(300_000, 0x72), folder.id);
    const selected = await session.api.get(`${base}/nodes/${folder.id}`);
    expect((await controls.put('/control/storage', { data: { method: 'PUT', contains: '/objects/', mode: 'pause' } })).status()).toBe(200);
    const pending = session.api.post(`${base}/nodes/${folder.id}:copy`, { headers: { 'idempotency-key': randomUUID(), 'if-match': selected.headers().etag },
      data: { parent_id: session.rootId, name: 'partial-result' } });
    await expect.poll(async () => (await (await controls.get('/control/storage')).json()).hits).toBe(1);
    const partial = await session.api.get(`${base}/nodes:resolve`, { params: { path: "/partial-result" } });
    expect(partial.status()).toBe(200);
    const copied = await partial.json();
    expect(copied.name).toBe('partial-result');
    const current = await session.api.get(`${base}/nodes/${file.node_id}`);
    expect((await session.api.put(`${base}/nodes/${file.node_id}/content`, { headers: { 'if-match': current.headers().etag, 'content-type': 'application/octet-stream' }, data: Buffer.from('changed') })).status()).toBe(200);
    await controls.delete('/control/storage');
    const failed = await pending;
    expect(failed.status()).toBe(409);
    await triggerStorageMaintenance();
    expect((await session.api.get(`${base}/nodes/${copied.id}`)).status()).toBe(200);
    expect((await (await session.api.get(`${base}/nodes`, { params: { parent_id: copied.id } })).json()).items).toEqual([]);
    expect((await (await session.api.get(`/v1/filesystems/${session.filesystemId}`)).json()).used_bytes).toBe('7');
  } finally { await controls.delete('/control/storage'); await storage.dispose(); }
});

test('a real CPU worker restart resumes object-source parsing without another artifact tree', async ({ session, controls, playwright }) => {
  const base = `/v1/filesystems/${session.filesystemId}/scopes/${session.scopeId}`;
  const bytes = recoveryGuide();
  const storage = await playwright.request.newContext();
  try {
    expect((await controls.put('/control/storage', { data: { method: 'GET', contains: '/objects/', mode: 'pause' } })).status()).toBe(200);
    const uploaded = await objectFile(session, storage, 'worker-recovery.docx', bytes, session.rootId,
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document');
    await expect.poll(async () => (await (await controls.get('/control/storage')).json()).hits).toBe(1);
    await restartService('ingest-cpu');
    await controls.delete('/control/storage');
    await expect.poll(async () => {
      const response = await session.api.get(`${base}/nodes/${uploaded.node_id}/processing`);
      expect(response.status()).toBe(200);
      const status = await response.json();
      return status.publication_status;
    }, { timeout: 150_000 }).toBe('ready');
    const state = await (await session.api.get(`${base}/nodes/${uploaded.node_id}/processing`)).json();
    const outputs = await session.api.get(`${base}/nodes`, { params: { parent_id: uploaded.node_id } });
    expect(outputs.status()).toBe(200);
    const children = (await outputs.json()).items;
    expect(children.filter((node: { name: string }) => node.name === 'README.md')).toHaveLength(1);
    expect(children.some((node: { name: string }) => node.name === 'artifacts')).toBe(false);
    const content = await session.api.get(`${base}/nodes/${uploaded.node_id}/content`, { maxRedirects: 0 });
    expect(content.status()).toBe(307);
    expect(await (await storage.get(content.headers().location)).body()).toEqual(bytes);
    await recordWorkflowHistory('ProcessFileRecovery', `process-file/${uploaded.node_id}/${state.desired_generation}`);
  } finally { await controls.delete('/control/storage'); await storage.dispose(); }
});

test('workspace deletion finishes after its HTTP caller disconnects', async ({ session, identity }) => {
  const base = `/v1/workspaces/${session.workspaceId}`;
  const release = await lockFilesystemRoot(session.filesystemId);
  let pending: Promise<unknown>;
  try {
    pending = session.api.delete(base, { timeout: 2000 }).catch(error => error);
    await expect.poll(() => filesystemDeletionIsRunning(session.workspaceId)).toBe(true);
    await pending;
  } finally { await release(); }
  await expect.poll(async () => (await session.api.get(base)).status()).toBe(403);
  expect((await session.api.get(`/v1/filesystems/${session.filesystemId}/scopes/${session.scopeId}/nodes/${session.rootId}`)).status()).toBe(404);
  await recordLifecycleHistories(identity.id, session.workspaceId);
});

test('a terminated Workspace deletion can be retried while its filesystem child remains active', async ({ session }) => {
  const base = `/v1/workspaces/${session.workspaceId}`;
  const release = await lockFilesystemRoot(session.filesystemId);
  const first = session.api.delete(base).catch(error => error);
  let retry: ReturnType<typeof session.api.delete> | undefined;
  try {
    await expect.poll(() => filesystemDeletionIsRunning(session.workspaceId)).toBe(true);
    await terminateWorkspaceDeletion(session.workspaceId);
    await first;
    retry = session.api.delete(base);
  } finally { await release(); }
  expect((await retry!).status()).toBe(204);
  expect((await session.api.get(base)).status()).toBe(403);
});
