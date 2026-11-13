import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { crc32c } from '@aws-crypto/crc32c';
import { test, expect } from '../../fixtures/api.js';

test('XLSX blob runs both workers, publishes readonly artifacts and becomes searchable', async ({
  account,
  request,
}) => {
  const { api, workspaceId, storageId, rootId } = account;
  const base = `/v1/workspaces/${workspaceId}/storages/${storageId}`;
  const bytes = readFileSync(new URL('../../fixtures/files/sample.xlsx', import.meta.url));
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32c(bytes));
  const preparation = {
    create: { parent: { nodeId: rootId }, name: 'sales.xlsx' },
    sizeBytes: String(bytes.length),
    mediaType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    checksum: checksum.toString('base64'),
    requestId: randomUUID(),
  };
  const prepared = await api.post(`${base}/uploads`, { data: preparation });
  expect(prepared.ok(), await prepared.text()).toBeTruthy();
  const upload = await prepared.json();
  const preparedAgain = await api.post(`${base}/uploads`, {
    data: preparation,
  });
  expect(preparedAgain.ok(), await preparedAgain.text()).toBeTruthy();
  expect(await preparedAgain.json()).toEqual(upload);
  const mismatched = await api.post(`${base}/uploads`, {
    data: { ...preparation, sizeBytes: String(bytes.length + 1) },
  });
  expect(mismatched.status()).toBe(409);
  const put = await request.put(upload.transfer.putUrl, {
    headers: upload.transfer.headers,
    data: bytes,
  });
  expect(put.ok(), await put.text()).toBeTruthy();
  const committed = await api.post(`${base}/uploads/${upload.id}:complete`, {
    data: {},
  });
  expect(committed.ok(), await committed.text()).toBeTruthy();
  const node = await committed.json();
  const replay = await api.post(`${base}/uploads/${upload.id}:complete`, {
    data: {},
  });
  expect(replay.ok(), await replay.text()).toBeTruthy();
  expect(await replay.json()).toEqual(node);
  await expect
    .poll(
      async () => {
        const current = await (await api.get(`${base}/nodes/${node.id}`)).json();
        expect(current.file.processing.errorCode).toBeUndefined();
        return current.file.processing.stage;
      },
      { timeout: 90_000 },
    )
    .toBe('ready');
  const tree = await api.post(`${base}/nodes:readTree`, {
    data: { root: { nodeId: node.id }, maxDepth: 8, maxNodes: 100 },
  });
  expect(tree.ok(), await tree.text()).toBeTruthy();
  const { entries } = await tree.json();
  const table = entries.find(
    (entry: { node: { name: string } }) => entry.node.name === 'revenue-report.csv',
  ).node;
  expect(table.readonly).toBe(true);
  expect(
    entries.some((entry: { path: string }) => entry.path === 'revenue-report/revenue-report.csv'),
  ).toBe(true);
  const sheetReadme = entries.find(
    (entry: { path: string }) => entry.path === 'revenue-report/README.md',
  ).node;
  const sheetContent = (await (await api.get(`${base}/nodes/${sheetReadme.id}/text`)).json())
    .content;
  expect(sheetContent).toContain('(revenue-report.csv)');
  expect(sheetContent).not.toContain('table-1.csv');
  expect((await (await api.get(`${base}/nodes/${table.id}/text`)).json()).content).toContain(
    'Europe,120',
  );
  expect(
    (
      await api.patch(`${base}/nodes/${table.id}/text`, {
        data: { append: 'denied', requestId: randomUUID() },
      })
    ).status(),
  ).toBeGreaterThanOrEqual(400);
  // Embedding fixtures rank CSV evidence below the root README; BM25 must recover it.
  const search = await api.post(`${base}/files:semanticSearch`, {
    data: { root: { nodeId: rootId }, query: 'csv', topK: 1 },
  });
  expect(search.ok(), await search.text()).toBeTruthy();
  const { hits } = await search.json();
  expect(hits).toHaveLength(1);
  const artifactPath = (id: string): string =>
    entries.find((entry: { path: string; node: { id: string } }) => entry.node.id === id).path;
  expect(hits[0].path).toBe(`sales.xlsx/${artifactPath(hits[0].node.id)}`);
  const scoped = await api.post(`${base}/files:semanticSearch`, {
    data: { root: { nodeId: node.id }, query: 'csv', topK: 1 },
  });
  expect(scoped.ok(), await scoped.text()).toBeTruthy();
  const scopedHit = (await scoped.json()).hits[0];
  expect(scopedHit.path).toBe(artifactPath(scopedHit.node.id));
  const textSearch = await api.post(`${base}/files:textSearch`, {
    data: { root: { nodeId: node.id }, query: 'Europe', pageSize: 100 },
  });
  expect(textSearch.ok(), await textSearch.text()).toBeTruthy();
  const textHits = (await textSearch.json()).hits;
  expect(
    textHits.some((hit: { path: string }) => hit.path === 'revenue-report/revenue-report.csv'),
  ).toBe(true);
  expect(hits[0].snippet).toContain('revenue-report.csv');
  const download = await api.get(`${base}/nodes/${node.id}:download`);
  const original = await request.get((await download.json()).blob.url);
  expect(await original.body()).toEqual(bytes);

  const payload = Buffer.alloc(20 * 1024 * 1024, 0x61);
  function crc(value: Buffer): string {
    const checksum = Buffer.alloc(4);
    checksum.writeUInt32BE(crc32c(value));
    return checksum.toString('base64');
  }
  const multipart = await api.post(`${base}/uploads`, {
    data: {
      create: { parent: { nodeId: rootId }, name: 'payload.bin' },
      sizeBytes: String(payload.length),
      mediaType: 'application/octet-stream',
      checksum: crc(payload),
      requestId: randomUUID(),
    },
  });
  expect(multipart.ok(), await multipart.text()).toBeTruthy();
  const transfer = await multipart.json();
  expect(transfer.transfer.multipart).toBe(true);
  const partSize = Number(transfer.transfer.partSizeBytes);
  const chunks: Buffer[] = [];
  for (let offset = 0; offset < payload.length; offset += partSize)
    chunks.push(payload.subarray(offset, offset + partSize));
  const parts = chunks.map((chunk, index) => ({
    partNumber: index + 1,
    checksum: crc(chunk),
  }));
  const signing = await api.post(`${base}/uploads/${transfer.id}:signParts`, {
    data: { parts },
  });
  expect(signing.ok(), await signing.text()).toBeTruthy();
  const signed = (await signing.json()).parts;
  const completed = [];
  for (const part of signed) {
    const put = await request.put(part.url, {
      headers: part.headers,
      data: chunks[part.partNumber - 1],
    });
    expect(put.ok(), await put.text()).toBeTruthy();
    completed.push({ ...parts[part.partNumber - 1], etag: put.headers().etag });
  }
  const publication = await api.post(`${base}/uploads/${transfer.id}:complete`, {
    data: { parts: completed },
  });
  expect(publication.ok(), await publication.text()).toBeTruthy();
  const published = await publication.json();
  const multipartDownload = await api.get(`${base}/nodes/${published.id}:download`);
  const downloaded = await request.get((await multipartDownload.json()).blob.url);
  expect(downloaded.ok(), await downloaded.text()).toBeTruthy();
  expect(await downloaded.body()).toEqual(payload);
});
