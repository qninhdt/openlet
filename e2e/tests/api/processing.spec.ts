import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { crc32c } from '@aws-crypto/crc32c';
import { test, expect } from '../../fixtures/api.js';

test('XLSX blob runs both workers, publishes readonly artifacts and becomes searchable', async ({ account, request }) => {
  const { api, workspaceId, storageId, rootId } = account;
  const base = `/v1/workspaces/${workspaceId}/storages/${storageId}`;
  const bytes = readFileSync(new URL('../../fixtures/files/sample.xlsx', import.meta.url));
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32c(bytes));
  const preparation = {
    create: { parent: { nodeId: rootId }, name: 'sales.xlsx' }, sizeBytes: String(bytes.length),
    mediaType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', checksum: checksum.toString('base64'), requestId: randomUUID(),
  };
  const prepared = await api.post(`${base}/uploads`, { data: preparation });
  expect(prepared.ok(), await prepared.text()).toBeTruthy();
  const upload = await prepared.json();
  const preparedAgain = await api.post(`${base}/uploads`, { data: preparation });
  expect(preparedAgain.ok(), await preparedAgain.text()).toBeTruthy();
  expect(await preparedAgain.json()).toEqual(upload);
  const mismatched = await api.post(`${base}/uploads`, { data: { ...preparation, sizeBytes: String(bytes.length + 1) } });
  expect(mismatched.status()).toBe(409);
  const put = await request.put(upload.transfer.putUrl, { headers: upload.transfer.headers, data: bytes });
  expect(put.ok(), await put.text()).toBeTruthy();
  const committed = await api.post(`${base}/uploads/${upload.id}:complete`, { data: {} });
  expect(committed.ok(), await committed.text()).toBeTruthy();
  const node = await committed.json();
  const replay = await api.post(`${base}/uploads/${upload.id}:complete`, { data: {} });
  expect(replay.ok(), await replay.text()).toBeTruthy();
  expect(await replay.json()).toEqual(node);
  await expect.poll(async () => {
    const current = await (await api.get(`${base}/nodes/${node.id}`)).json();
    expect(current.file.processing.errorCode).toBeUndefined();
    return current.file.processing.stage;
  }, { timeout: 90_000 }).toBe('ready');
  const tree = await api.post(`${base}/nodes:readTree`, { data: { root: { nodeId: node.id }, maxDepth: 8, maxNodes: 100 } });
  expect(tree.ok(), await tree.text()).toBeTruthy();
  const { entries } = await tree.json();
  const table = entries.find((entry: { node: { name: string } }) => entry.node.name === 'table-1.csv').node;
  expect(table.readonly).toBe(true);
  expect((await (await api.get(`${base}/nodes/${table.id}/text`)).json()).content).toContain('Europe,120');
  expect((await api.patch(`${base}/nodes/${table.id}/text`, { data: { append: 'denied', requestId: randomUUID() } })).status()).toBeGreaterThanOrEqual(400);
  // Embedding fixtures rank CSV evidence below the root README; BM25 must recover it.
  const search = await api.post(`${base}/files:semanticSearch`, { data: { root: { nodeId: rootId }, query: 'csv', topK: 1 } });
  expect(search.ok(), await search.text()).toBeTruthy();
  const { hits } = await search.json();
  expect(hits).toHaveLength(1);
  expect(hits[0].snippet).toContain('table-1.csv');
  const download = await api.get(`${base}/nodes/${node.id}:download`);
  const original = await request.get((await download.json()).blob.url);
  expect(await original.body()).toEqual(bytes);
});
