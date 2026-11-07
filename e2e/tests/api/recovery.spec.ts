import { randomUUID } from 'node:crypto';
import { test, expect, directory, objectFile, inline } from '../../fixtures/api-test.ts';
import { lockFilesystemRoot } from '../../fixtures/filesystem-lock.ts';
import { recoveryGuide } from '../../fixtures/documents.ts';
import { restartService } from '../../fixtures/restart-service.ts';
import { setTemporalRunning, temporalIsHealthy, triggerStorageMaintenance, recordCopyHistory, recordLifecycleHistories, recordWorkflowHistory, filesystemDeletionIsRunning, terminateWorkspaceDeletion } from '../../fixtures/temporal-control.ts';

test('copy admission survives a Temporal outage and maintenance starts the committed receipt', async ({ session }) => {
  const base = `/v1/filesystems/${session.filesystemId}/scopes/${session.scopeId}`;
  const source = await inline(session, 'deferred-source.bin', Buffer.from('copy'));
  const options = { headers: { 'idempotency-key': randomUUID(), 'if-match': '"1"' }, data: { source_id: source.id, parent_id: session.rootId, name: 'deferred-copy.bin' } };
  await setTemporalRunning(false);
  try {
    const admitted = await session.api.post(`${base}/nodes`, options);
    expect(admitted.status()).toBe(503);
  } finally { await setTemporalRunning(true); }
  await expect.poll(temporalIsHealthy).toBe(true);
  await triggerStorageMaintenance();
  await expect.poll(async () => (await session.api.get(`${base}/nodes:resolve`, { params: { path: '/deferred-copy.bin' } })).status()).toBe(200);
  const repeated = await session.api.post(`${base}/nodes`, options);
  expect(repeated.status()).toBe(202);
  const copy = await repeated.json();
  await recordCopyHistory('CopyTreeDeferred', session.filesystemId, copy.id);
  expect(await (await session.api.get(`${base}/nodes/${copy.destination_root_id}/content`)).body()).toEqual(Buffer.from('copy'));
  expect((await (await session.api.get(`/v1/filesystems/${session.filesystemId}`)).json()).used_bytes).toBe('8');
});

test('source changes and a real worker restart leave committed partial copy visible', async ({ session, controls, playwright }) => {
  const base = `/v1/filesystems/${session.filesystemId}/scopes/${session.scopeId}`;
  const folder = await directory(session, 'changing-source');
  const storage = await playwright.request.newContext();
  try {
    const file = await objectFile(session, storage, 'source.bin', Buffer.alloc(300_000, 0x72), folder.id);
    const selected = await session.api.get(`${base}/nodes/${folder.id}`);
    expect((await controls.put('/control/storage', { data: { method: 'PUT', contains: '/objects/', mode: 'pause' } })).status()).toBe(200);
    const admitted = await session.api.post(`${base}/nodes`, { headers: { 'idempotency-key': randomUUID(), 'if-match': selected.headers().etag },
      data: { source_id: folder.id, parent_id: session.rootId, name: 'partial-result' } });
    expect(admitted.status()).toBe(202);
    const copy = await admitted.json();
    await expect.poll(async () => (await (await controls.get('/control/storage')).json()).hits).toBe(1);
    const partial = await session.api.get(`${base}/nodes/${copy.destination_root_id}`);
    expect(partial.status()).toBe(200);
    expect((await partial.json()).name).toBe('partial-result');
    const current = await session.api.get(`${base}/nodes/${file.node_id}`);
    expect((await session.api.put(`${base}/nodes/${file.node_id}/content`, { headers: { 'if-match': current.headers().etag, 'content-type': 'application/octet-stream' }, data: Buffer.from('changed') })).status()).toBe(200);
    await restartService('letfs');
    await controls.delete('/control/storage');
    await recordCopyHistory('CopyTreeRecovery', session.filesystemId, copy.id, true);
    expect((await session.api.get(`${base}/nodes/${copy.destination_root_id}`)).status()).toBe(200);
    expect((await (await session.api.get(`${base}/nodes`, { params: { parent_id: copy.destination_root_id } })).json()).items).toEqual([]);
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
