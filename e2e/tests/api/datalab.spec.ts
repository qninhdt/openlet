import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { crc32c } from '@aws-crypto/crc32c';
import { test, expect } from '../../fixtures/api.js';

for (const [extension, mediaType] of [
  ['pdf', 'application/pdf'],
  ['docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
]) {
  test(`${extension.toUpperCase()} publishes Datalab Markdown`, async ({ account, request }) => {
    const { api, workspaceId, storageId, rootId } = account;
    const base = `/v1/workspaces/${workspaceId}/storages/${storageId}`;
    const name = `sample.${extension}`;
    const bytes = readFileSync(new URL(`../../fixtures/files/${name}`, import.meta.url));
    const checksum = Buffer.alloc(4);
    checksum.writeUInt32BE(crc32c(bytes));
    const prepared = await api.post(`${base}/uploads`, {
      data: {
        create: { parent: { nodeId: rootId }, name },
        sizeBytes: String(bytes.length),
        mediaType,
        checksum: checksum.toString('base64'),
        requestId: randomUUID(),
      },
    });
    expect(prepared.ok(), await prepared.text()).toBeTruthy();
    const upload = await prepared.json();
    const put = await request.put(upload.transfer.putUrl, {
      headers: upload.transfer.headers,
      data: bytes,
    });
    expect(put.ok(), await put.text()).toBeTruthy();
    const completed = await api.post(`${base}/uploads/${upload.id}:complete`, { data: {} });
    expect(completed.ok(), await completed.text()).toBeTruthy();
    const node = await completed.json();
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
    const readme = entries.find((entry: { path: string }) => entry.path === 'README.md');
    expect(readme).toBeDefined();
    const artifact = await api.get(`${base}/nodes/${readme.node.id}/text`);
    expect(artifact.ok(), await artifact.text()).toBeTruthy();
    expect((await artifact.json()).content).toContain(
      `Datalab ${extension.toUpperCase()} extract.`,
    );
  });
}
