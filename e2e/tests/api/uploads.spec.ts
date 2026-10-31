import { createHash, randomUUID } from 'node:crypto';
import { test, expect, inline } from '../../fixtures/api-test.ts';

test('single object upload finalizes once and preserves exact download and Range bytes', async ({ session, playwright }) => {
  const base = `/v1/workspaces/${session.workspaceId}`;
  const bytes = Buffer.alloc(300_000, 0xab);
  bytes.write('direct upload with exact binary bytes');
  const key = randomUUID();
  const options = { headers: { 'idempotency-key': key }, data: { parent_id: session.rootId, name: 'object.bin',
    media_type: 'application/octet-stream', size_bytes: String(bytes.length), content_md5: createHash('md5').update(bytes).digest('base64') } };
  const prepared = await session.api.post(`${base}/uploads`, options);
  expect(prepared.status()).toBe(201);
  const upload = await prepared.json();
  expect(upload).toMatchObject({ status: 'open', transport: 'single' });
  const repeated = await session.api.post(`${base}/uploads`, options);
  expect(repeated.status()).toBe(201);
  expect((await repeated.json()).id).toBe(upload.id);
  const storage = await playwright.request.newContext();
  try {
    const sent = await storage.put(upload.transfer.url, { headers: upload.transfer.headers, data: bytes });
    expect(sent.status()).toBe(200);
    const completion = await session.api.put(`${base}/uploads/${upload.id}/completion`, { data: {} });
    expect(completion.status()).toBe(200);
    const result = await completion.json();
    expect(result).toMatchObject({ status: 'finalized', node_id: expect.any(String) });
    const replay = await session.api.put(`${base}/uploads/${upload.id}/completion`, { data: {} });
    expect(replay.status()).toBe(200);
    expect(await replay.json()).toEqual(result);
    const redirect = await session.api.get(`${base}/nodes/${result.node_id}/content`, { maxRedirects: 0 });
    expect(redirect.status()).toBe(307);
    expect(redirect.headers()['cache-control']).toContain('no-store');
    const downloaded = await storage.get(redirect.headers().location);
    expect(downloaded.status()).toBe(200);
    expect(await downloaded.body()).toEqual(bytes);
    const range = await storage.get(redirect.headers().location, { headers: { range: 'bytes=17-31' } });
    expect(range.status()).toBe(206);
    expect(await range.body()).toEqual(bytes.subarray(17, 32));
    expect((await (await session.api.get(`${base}/storage`)).json()).used_bytes).toBe(String(bytes.length));
  } finally { await storage.dispose(); }
});

test('stale object replacement preserves the intervening content and quota', async ({ session, playwright }) => {
  const base = `/v1/workspaces/${session.workspaceId}`;
  const original = await inline(session, 'replace.bin', Buffer.from('original'));
  const selected = await session.api.get(`${base}/nodes/${original.id}`);
  const candidate = Buffer.alloc(300_000, 0x63);
  const admitted = await session.api.post(`${base}/uploads`, { headers: { 'idempotency-key': randomUUID(), 'if-match': selected.headers().etag },
    data: { node_id: original.id, size_bytes: String(candidate.length), media_type: 'application/octet-stream', content_md5: createHash('md5').update(candidate).digest('base64') } });
  expect(admitted.status()).toBe(201);
  const upload = await admitted.json();
  const storage = await playwright.request.newContext();
  try {
    expect((await storage.put(upload.transfer.url, { headers: upload.transfer.headers, data: candidate })).status()).toBe(200);
    const intervening = Buffer.from('newer content');
    const updated = await session.api.put(`${base}/nodes/${original.id}/content`, { headers: { 'if-match': selected.headers().etag, 'content-type': 'application/octet-stream' }, data: intervening });
    expect(updated.status()).toBe(200);
    const rejected = await session.api.put(`${base}/uploads/${upload.id}/completion`, { data: {} });
    expect(rejected.status()).toBe(412);
    expect(await (await session.api.get(`${base}/nodes/${original.id}/content`)).body()).toEqual(intervening);
    expect((await (await session.api.get(`${base}/storage`)).json()).used_bytes).toBe(String(intervening.length));
    expect((await session.api.delete(`${base}/uploads/${upload.id}`)).status()).toBe(204);
  } finally { await storage.dispose(); }
});

test('native multipart completion reconciles a lost S3 acknowledgment without republishing or charging twice', async ({ session, controls, playwright }) => {
  const base = `/v1/workspaces/${session.workspaceId}`;
  const bytes = Buffer.alloc(17 * 1024 * 1024, 0x6d);
  const prepared = await session.api.post(`${base}/uploads`, { headers: { 'idempotency-key': randomUUID() },
    data: { parent_id: session.rootId, name: 'multipart.bin', media_type: 'application/octet-stream', size_bytes: String(bytes.length) } });
  expect(prepared.status()).toBe(201);
  const upload = await prepared.json();
  expect(upload.transport).toBe('multipart');
  const numbers = Array.from({ length: upload.part_count }, (_, index) => index + 1);
  const signed = await session.api.get(`${base}/uploads/${upload.id}/parts`, { params: { numbers: numbers.join(',') } });
  expect(signed.status()).toBe(200);
  expect(signed.headers()['cache-control']).toContain('no-store');
  const urls = (await signed.json()).items;
  expect(urls).toHaveLength(numbers.length);
  const receipts: { part_number: number; etag: string }[] = [];
  const storage = await playwright.request.newContext();
  try {
    for (const part of urls) {
      const start = (part.part_number - 1) * Number(upload.part_size_bytes);
      const response = await storage.put(part.transfer.url, { headers: part.transfer.headers, data: bytes.subarray(start, start + Number(upload.part_size_bytes)) });
      expect(response.status()).toBe(200);
      expect(response.headers().etag).toEqual(expect.any(String));
      receipts.push({ part_number: part.part_number, etag: response.headers().etag });
    }
    expect((await controls.put('/control/storage', { data: { method: 'POST', contains: 'uploadId=', mode: 'drop-response' } })).status()).toBe(200);
    const completed = await session.api.put(`${base}/uploads/${upload.id}/completion`, { data: { parts: receipts }, timeout: 150_000 });
    expect(completed.status()).toBe(200);
    const result = await completed.json();
    expect((await (await controls.get('/control/storage')).json()).hits).toBe(1);
    const replay = await session.api.put(`${base}/uploads/${upload.id}/completion`, { data: {} });
    expect(replay.status()).toBe(200);
    expect(await replay.json()).toEqual(result);
    const status = await session.api.get(`${base}/uploads/${upload.id}`);
    expect(await status.json()).toMatchObject({ status: 'finalized', result: { node_id: result.node_id } });
    const redirect = await session.api.get(`${base}/nodes/${result.node_id}/content`, { maxRedirects: 0 });
    expect(redirect.status()).toBe(307);
    const downloaded = await storage.get(redirect.headers().location);
    expect(downloaded.status()).toBe(200);
    expect(await downloaded.body()).toEqual(bytes);
    expect((await (await session.api.get(`${base}/storage`)).json()).used_bytes).toBe(String(bytes.length));
  } finally {
    await controls.delete('/control/storage');
    await storage.dispose();
  }
});

test('quota rejection at publication retains the committed file and does not charge the candidate', async ({ session, playwright }) => {
  const base = `/v1/workspaces/${session.workspaceId}`;
  const storage = await playwright.request.newContext();
  const bytes = Buffer.alloc(12 * 1024 * 1024, 0x71);
  try {
    const first = await session.api.post(`${base}/uploads`, { headers: { 'idempotency-key': randomUUID() },
      data: { parent_id: session.rootId, name: 'first.bin', size_bytes: String(bytes.length), media_type: 'application/octet-stream', content_md5: createHash('md5').update(bytes).digest('base64') } });
    expect(first.status()).toBe(201);
    const second = await session.api.post(`${base}/uploads`, { headers: { 'idempotency-key': randomUUID() },
      data: { parent_id: session.rootId, name: 'second.bin', size_bytes: String(bytes.length), media_type: 'application/octet-stream', content_md5: createHash('md5').update(bytes).digest('base64') } });
    expect(second.status()).toBe(201);
    const a = await first.json();
    const b = await second.json();
    for (const upload of [a, b]) expect((await storage.put(upload.transfer.url, { headers: upload.transfer.headers, data: bytes })).status()).toBe(200);
    const published = await session.api.put(`${base}/uploads/${a.id}/completion`, { data: {} });
    expect(published.status()).toBe(200);
    const rejected = await session.api.put(`${base}/uploads/${b.id}/completion`, { data: {} });
    expect(rejected.status()).toBe(409);
    expect(await rejected.json()).toMatchObject({ code: 'QUOTA_EXCEEDED' });
    const nodes = await session.api.get(`${base}/nodes`, { params: { parent_id: session.rootId } });
    expect((await nodes.json()).items.map((node: { name: string }) => node.name)).toEqual(['first.bin']);
    expect((await (await session.api.get(`${base}/storage`)).json()).used_bytes).toBe(String(bytes.length));
    const content = await session.api.get(`${base}/nodes/${(await published.json()).node_id}/content`, { maxRedirects: 0 });
    expect(content.status()).toBe(307);
    expect(await (await storage.get(content.headers().location)).body()).toEqual(bytes);
    expect((await session.api.delete(`${base}/uploads/${b.id}`)).status()).toBe(204);
  } finally { await storage.dispose(); }
});
