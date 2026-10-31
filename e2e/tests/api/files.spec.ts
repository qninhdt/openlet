import { recordCopyHistory, recordWorkflowHistory } from '../../fixtures/temporal-control.ts';
import { randomUUID } from 'node:crypto';
import { unzipSync } from 'fflate';
import { test, expect, directory, inline, objectFile } from '../../fixtures/api-test.ts';

test('strict create preserves exact inline bytes, namespace uniqueness and revision preconditions', async ({ session }) => {
  const base = `/v1/workspaces/${session.workspaceId}`;
  const bytes = Buffer.from([0, 255, 13, 10, 65, 0]);
  const key = randomUUID();
  const data = { kind: 'file', parent_id: session.rootId, name: 'payload.bin', content_base64: bytes.toString('base64'), media_type: 'application/octet-stream' };
  const create = await session.api.post(`${base}/nodes`, { headers: { 'idempotency-key': key }, data });
  expect(create.status()).toBe(201);
  const node = await create.json();
  const etag = create.headers().etag;
  const replay = await session.api.post(`${base}/nodes`, { headers: { 'idempotency-key': key }, data });
  expect(replay.status()).toBe(201);
  expect((await replay.json()).id).toBe(node.id);
  const collision = await session.api.post(`${base}/nodes`, { headers: { 'idempotency-key': randomUUID() }, data });
  expect(collision.status()).toBe(409);
  const mismatch = await session.api.post(`${base}/nodes`, { headers: { 'idempotency-key': key }, data: { ...data, name: 'another.bin' } });
  expect(mismatch.status()).toBe(409);
  const content = await session.api.get(`${base}/nodes/${node.id}/content`);
  expect(content.status()).toBe(200);
  expect(await content.body()).toEqual(bytes);
  const range = await session.api.get(`${base}/nodes/${node.id}/content`, { headers: { range: 'bytes=1-3' } });
  expect(range.status()).toBe(206);
  expect(await range.body()).toEqual(Buffer.from([255, 13, 10]));
  expect((await session.api.patch(`${base}/nodes/${node.id}`, { data: { name: 'renamed.bin' } })).status()).toBe(428);
  const renamed = await session.api.patch(`${base}/nodes/${node.id}`, { headers: { 'if-match': etag }, data: { name: 'renamed.bin' } });
  expect(renamed.status()).toBe(200);
  expect(renamed.headers().etag).not.toBe(etag);
  const destination = await directory(session, 'destination');
  const moved = await session.api.patch(`${base}/nodes/${node.id}`, { headers: { 'if-match': renamed.headers().etag }, data: { parent_id: destination.id } });
  expect(moved.status()).toBe(200);
  expect(await moved.json()).toMatchObject({ id: node.id, parent_id: destination.id });
  const stale = await session.api.put(`${base}/nodes/${node.id}/content`, { headers: { 'if-match': etag, 'content-type': 'application/octet-stream' }, data: Buffer.from('stale') });
  expect(stale.status()).toBe(412);
  expect(await (await session.api.get(`${base}/nodes/${node.id}/content`)).body()).toEqual(bytes);
  const usage = await session.api.get(`${base}/storage`);
  expect((await usage.json()).used_bytes).toBe(String(bytes.length));
  const replacement = Buffer.from([255, 0, 128, 13, 10, 0, 17]);
  const updated = await session.api.put(`${base}/nodes/${node.id}/content`, {
    headers: { 'if-match': moved.headers().etag, 'content-type': 'text/html' }, data: replacement,
  });
  expect(updated.status()).toBe(200);
  const reread = await session.api.get(`${base}/nodes/${node.id}/content`);
  expect(await reread.body()).toEqual(replacement);
  expect(reread.headers()['content-type']).toBe('text/html');
  expect(reread.headers()['content-disposition']).toContain('attachment');
  expect(reread.headers()['x-content-type-options']).toBe('nosniff');
  expect((await (await session.api.get(`${base}/storage`)).json()).used_bytes).toBe(String(replacement.length));
});

test('copy commits ordinary nodes with stable identity, exact bytes and accounting across Continue-As-New', async ({ session }) => {
  const base = `/v1/workspaces/${session.workspaceId}`;
  const folder = await directory(session, 'source');
  const bytes = Buffer.from('copy must retain these bytes\r\n');
  for (let index = 0; index < 40; index++) await inline(session, `data-${index}.bin`, bytes, folder.id);
  const selected = await session.api.get(`${base}/nodes/${folder.id}`);
  const key = randomUUID();
  const options = { headers: { 'idempotency-key': key, 'if-match': selected.headers().etag }, data: { source_id: folder.id, parent_id: session.rootId, name: 'copied' } };
  const copied = await session.api.post(`${base}/nodes`, options);
  expect(copied.status()).toBe(202);
  const copy = await copied.json();
  const monitor = copied.headers().location;
  expect(monitor).toBe(`${base}/copies/${copy.id}`);
  const repeated = await session.api.post(`${base}/nodes`, options);
  expect(repeated.status()).toBe(202);
  expect((await repeated.json()).id).toBe(copy.id);
  await expect.poll(async () => (await (await session.api.get(monitor)).json()).status).toBe('succeeded');
  const result = await (await session.api.get(monitor)).json();
  expect(result).toMatchObject({ committed_nodes: '41', committed_bytes: String(bytes.length * 40) });
  await recordCopyHistory('CopyNode', folder.filesystem_id, copy.id, true);
  const contents = await (await session.api.get(`${base}/nodes`, { params: { parent_id: result.destination_root_id } })).json();
  expect(contents.items).toHaveLength(40);
  expect(await (await session.api.get(`${base}/nodes/${contents.items[0].id}/content`)).body()).toEqual(bytes);
  expect((await (await session.api.get(`${base}/storage`)).json()).used_bytes).toBe(String(bytes.length * 80));
});

test('object copy retries a lost S3 acknowledgment without duplicate bytes or quota', async ({ session, controls, playwright }) => {
  const base = `/v1/workspaces/${session.workspaceId}`;
  const storage = await playwright.request.newContext();
  const bytes = Buffer.alloc(300_000, 0x45);
  try {
    const source = await objectFile(session, storage, 'copy-source.bin', bytes);
    expect((await controls.put('/control/storage', { data: { method: 'PUT', contains: '/objects/', mode: 'drop-response' } })).status()).toBe(200);
    const admitted = await session.api.post(`${base}/nodes`, { headers: { 'idempotency-key': randomUUID(), 'if-match': '"1"' }, data: { source_id: source.node_id, parent_id: session.rootId, name: 'copy-result.bin' } });
    expect(admitted.status()).toBe(202);
    const copy = await admitted.json();
    await expect.poll(async () => (await (await session.api.get(admitted.headers().location)).json()).status).toBe('succeeded');
    expect((await (await controls.get('/control/storage')).json()).hits).toBe(1);
    const downloaded = await session.api.get(`${base}/nodes/${copy.destination_root_id}/content`, { maxRedirects: 0 });
    expect(downloaded.status()).toBe(307);
    expect(await (await storage.get(downloaded.headers().location)).body()).toEqual(bytes);
    expect((await (await session.api.get(`${base}/storage`)).json()).used_bytes).toBe(String(bytes.length * 2));
  } finally { await controls.delete('/control/storage'); await storage.dispose(); }
});

test('trash entries preserve identity through restore and purge only debit removed content', async ({ session }) => {
  const base = `/v1/workspaces/${session.workspaceId}`;
  const folder = await directory(session, 'trash-resource');
  const bytes = Buffer.from([0, 255, 19]);
  const file = await inline(session, 'retained.bin', bytes, folder.id);
  const selected = await session.api.get(`${base}/nodes/${folder.id}`);
  const trashed = await session.api.delete(`${base}/nodes/${folder.id}`, { headers: { 'if-match': selected.headers().etag } });
  expect(trashed.status()).toBe(201);
  const entry = await trashed.json();
  expect(entry).toMatchObject({ node_id: folder.id, parent_id: session.rootId, name: 'trash-resource', status: 'trashed', actor_id: session.userId });
  expect(trashed.headers().location).toBe(`${base}/trash-entries/${entry.id}`);
  expect((await session.api.get(`${base}/nodes/${file.id}`)).status()).toBe(404);
  expect((await (await session.api.get(`${base}/storage`)).json()).used_bytes).toBe('3');
  expect(await (await session.api.get(trashed.headers().location)).json()).toEqual(entry);
  const restored = await session.api.post(`${base}/trash-entries/${entry.id}:restore`);
  expect(restored.status()).toBe(200);
  expect((await restored.json()).id).toBe(folder.id);
  expect(await (await session.api.get(`${base}/nodes/${file.id}/content`)).body()).toEqual(bytes);
  expect((await session.api.get(`${base}/trash-entries/${entry.id}`)).status()).toBe(404);
  const current = await session.api.get(`${base}/nodes/${folder.id}`);
  const next = await session.api.delete(`${base}/nodes/${folder.id}`, { headers: { 'if-match': current.headers().etag } });
  expect(next.status()).toBe(201);
  const nextEntry = await next.json();
  expect(nextEntry.id).not.toBe(entry.id);
  expect((await session.api.post(`${base}/trash-entries/${entry.id}:restore`)).status()).toBe(404);
  const purge = await session.api.delete(`${base}/trash-entries/${nextEntry.id}`);
  expect(purge.status()).toBe(202);
  expect(await purge.json()).toMatchObject({ id: nextEntry.id, status: 'purging' });
  await expect.poll(async () => (await session.api.get(purge.headers().location)).status()).toBe(404);
  expect((await (await session.api.get(`${base}/storage`)).json()).used_bytes).toBe('0');
  expect((await session.api.delete(`${base}/trash-entries/${nextEntry.id}`)).status()).toBe(204);
  expect((await session.api.post(`${base}/trash-entries/${nextEntry.id}:restore`)).status()).toBe(404);
  await recordWorkflowHistory('PurgeTrash', `purge-trash/${folder.filesystem_id}/${nextEntry.id}`);
});

test('ZIP streams exact relative paths and empty directories through the gateway', async ({ session }) => {
  const base = `/v1/workspaces/${session.workspaceId}`;
  const folder = await directory(session, 'download');
  await directory(session, 'empty', folder.id);
  const bytes = Buffer.from('ZIP payload\0\r\n', 'utf8');
  await inline(session, 'tài-liệu.bin', bytes, folder.id);
  const response = await session.api.get(`${base}/nodes/${folder.id}/archive`);
  expect(response.status()).toBe(200);
  expect(response.headers()['content-type']).toContain('application/zip');
  const entries = unzipSync(await response.body());
  expect(Object.keys(entries).sort()).toEqual(['empty/', 'tài-liệu.bin'].sort());
  expect(Buffer.from(entries['tài-liệu.bin'])).toEqual(bytes);
  expect(entries['empty/']).toHaveLength(0);
  const usage = await session.api.get(`${base}/storage`);
  expect((await usage.json()).used_bytes).toBe(String(bytes.length));
});

test('copy into an occupied destination rejects without changing existing content or quota', async ({ session }) => {
  const base = `/v1/workspaces/${session.workspaceId}`;
  const source = await inline(session, 'source.bin', Buffer.from('source'));
  const occupied = await inline(session, 'occupied.bin', Buffer.from('keep'));
  const selected = await session.api.get(`${base}/nodes/${source.id}`);
  const response = await session.api.post(`${base}/nodes`, {
    headers: { 'idempotency-key': randomUUID(), 'if-match': selected.headers().etag },
    data: { source_id: source.id, parent_id: session.rootId, name: 'occupied.bin' },
  });
  expect(response.status()).toBe(409);
  expect(await response.json()).toMatchObject({ code: 'NAME_CONFLICT' });
  expect(await (await session.api.get(`${base}/nodes/${occupied.id}/content`)).body()).toEqual(Buffer.from('keep'));
  expect((await (await session.api.get(`${base}/storage`)).json()).used_bytes).toBe('10');
});

test('mounted paths, relative cwd and root ID aliases resolve the same scoped node', async ({ session }) => {
  const base = `/v1/workspaces/${session.workspaceId}`;
  const folder = await directory(session, 'paths');
  const file = await inline(session, 'bytes.bin', Buffer.from([0, 255, 17]), folder.id);
  const locators: Record<string, string>[] = [
    { path: '/drive/paths/bytes.bin' },
    { path: './bytes.bin', cwd_id: folder.id },
    { path: `/drive/@${file.id}` },
  ];
  for (const params of locators) {
    const response = await session.api.get(`${base}/nodes:resolve`, { params });
    expect(response.status()).toBe(200);
    expect(await response.json()).toMatchObject({ id: file.id, parent_id: folder.id, kind: 'file' });
  }
  const children = await session.api.get(`${base}/nodes`, { params: { path: './paths', cwd_id: session.rootId } });
  expect(children.status()).toBe(200);
  expect((await children.json()).items.map((node: { id: string }) => node.id)).toEqual([file.id]);
  const mismatch = await session.api.get(`${base}/nodes:resolve`, { params: { path: '/drive/paths/bytes.bin', expected_node_id: folder.id } });
  expect(mismatch.status()).toBe(409);
});
