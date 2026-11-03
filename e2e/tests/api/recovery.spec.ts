import { randomUUID } from 'node:crypto';
import { test, expect, directory, objectFile, inline } from '../../fixtures/api-test.ts';
import { lockFilesystemRoot } from '../../fixtures/filesystem-lock.ts';
import { recoveryGuide } from '../../fixtures/documents.ts';
import { restartService } from '../../fixtures/restart-service.ts';
import { setTemporalRunning, temporalIsHealthy, triggerStorageMaintenance, recordCopyHistory, recordLifecycleHistories, recordWorkflowHistory, workspaceDeletionHasChild, terminateWorkspaceDeletion } from '../../fixtures/temporal-control.ts';

test('copy admission survives a Temporal outage and maintenance starts the committed receipt', async ({ session }) => {
  const base = `/v1/filesystems/${session.filesystemId}`;
  const source = await inline(session, 'deferred-source.bin', Buffer.from('copy'));
  const options = { headers: { 'idempotency-key': randomUUID(), 'if-match': '"1"' }, data: { source_id: source.id, parent_id: session.rootId, name: 'deferred-copy.bin' } };
  let id: string;
  let monitor: string;
  await setTemporalRunning(false);
  try {
    const admitted = await session.api.post(`${base}/nodes`, options);
    expect(admitted.status()).toBe(202);
    const body = await admitted.json();
    expect(body).toMatchObject({ status: 'accepted', committed_nodes: '0', committed_bytes: '0' });
    id = body.id;
    monitor = admitted.headers().location;
    const repeated = await session.api.post(`${base}/nodes`, options);
    expect(repeated.status()).toBe(202);
    expect(await repeated.json()).toEqual(body);
  } finally { await setTemporalRunning(true); }
  await expect.poll(temporalIsHealthy).toBe(true);
  await triggerStorageMaintenance();
  await expect.poll(async () => {
    const response = await session.api.get(monitor);
    return response.status() === 200 ? (await response.json()).status : 'starting';
  }).toBe('succeeded');
  expect(await (await session.api.get(monitor)).json()).toMatchObject({ id, committed_nodes: '1', committed_bytes: '4' });
  expect((await (await session.api.get(`/v1/quota-buckets/${session.bucketId}`)).json()).bucket.used_bytes).toBe('8');
});

test('source changes and a real worker restart leave committed partial copy visible', async ({ session, controls, playwright }) => {
  const base = `/v1/filesystems/${session.filesystemId}`;
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
    const monitor = admitted.headers().location;
    await expect.poll(async () => (await (await controls.get('/control/storage')).json()).hits).toBe(1);
    const partial = await session.api.get(`${base}/nodes/${copy.destination_root_id}`);
    expect(partial.status()).toBe(200);
    expect((await partial.json()).name).toBe('partial-result');
    const current = await session.api.get(`${base}/nodes/${file.node_id}`);
    expect((await session.api.put(`${base}/nodes/${file.node_id}/content`, { headers: { 'if-match': current.headers().etag, 'content-type': 'application/octet-stream' }, data: Buffer.from('changed') })).status()).toBe(200);
    await restartService('letfs');
    await controls.delete('/control/storage');
    await expect.poll(async () => {
      const response = await session.api.get(monitor);
      return response.status() === 200 ? (await response.json()).status : 'restarting';
    }).toBe('failed');
    const result = await (await session.api.get(monitor)).json();
    expect(result).toMatchObject({ destination_root_id: copy.destination_root_id, committed_nodes: '1', committed_bytes: '0', error_code: 'SOURCE_REPLACED' });
    await recordCopyHistory('CopyNodeRecovery', folder.filesystem_id, copy.id);
    expect((await session.api.get(`${base}/nodes/${copy.destination_root_id}`)).status()).toBe(200);
    expect((await (await session.api.get(`${base}/nodes`, { params: { parent_id: copy.destination_root_id } })).json()).items).toEqual([]);
    expect((await (await session.api.get(`/v1/quota-buckets/${session.bucketId}`)).json()).bucket.used_bytes).toBe('7');
  } finally { await controls.delete('/control/storage'); await storage.dispose(); }
});

test('a real CPU worker restart resumes object-source parsing without another artifact tree', async ({ session, controls, playwright }) => {
  const base = `/v1/filesystems/${session.filesystemId}`;
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

test('workspace deletion remains admitted after the client stops polling', async ({ session, identity }) => {
  const base = `/v1/workspaces/${session.workspaceId}`;
  const selected = await session.api.get(base);
  expect((await session.api.delete(base)).status()).toBe(428);
  const response = await session.api.delete(base, { headers: { 'if-match': selected.headers().etag } });
  expect(response.status()).toBe(202);
  expect(response.headers().location).toBe(base);
  expect(await response.json()).toMatchObject({ id: session.workspaceId, status: 'deleting' });
  const repeated = await session.api.delete(base, { headers: { 'if-match': selected.headers().etag } });
  expect([202, 204]).toContain(repeated.status());
  await expect.poll(async () => {
    const current = await session.api.get(base);
    return current.status() === 404 ? 'deleted' : (await current.json()).status;
  }).toBe('deleted');
  expect((await session.api.delete(base, { headers: { 'if-match': selected.headers().etag } })).status()).toBe(204);
  const workspaces = await session.api.get('/v1/workspaces');
  expect((await workspaces.json()).items).not.toContainEqual(expect.objectContaining({ id: session.workspaceId }));
  expect((await session.api.get(`/v1/filesystems/${session.filesystemId}/nodes/${session.rootId}`)).status()).toBe(403);
  await recordLifecycleHistories(identity.id, session.workspaceId);
});

test('a terminated Workspace parent resumes cleanup while its filesystem child remains active', async ({ session }) => {
  const base = `/v1/workspaces/${session.workspaceId}`;
  const selected = await session.api.get(base);
  const headers = { 'if-match': selected.headers().etag };
  const release = await lockFilesystemRoot((await selected.json()).filesystem_id);
  try {
    expect((await session.api.delete(base, { headers })).status()).toBe(202);
    await expect.poll(() => workspaceDeletionHasChild(session.workspaceId)).toBe(true);
    await terminateWorkspaceDeletion(session.workspaceId);
    expect((await session.api.delete(base, { headers })).status()).toBe(202);
  } finally { await release(); }
  await expect.poll(async () => (await (await session.api.get(base)).json()).status).toBe('deleted');
});
