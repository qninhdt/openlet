import { randomUUID } from 'node:crypto';
import { test, expect, inline } from '../../fixtures/api-test.ts';
import { recoveryGuide } from '../../fixtures/documents.ts';
import { recordWorkflowHistory } from '../../fixtures/temporal-control.ts';

test('real document parsing publishes README semantics and current searchable content', async ({ session }) => {
  const base = `/v1/workspaces/${session.workspaceId}`;
  const bytes = recoveryGuide();
  const source = await inline(session, 'recovery-guide.docx', bytes, session.rootId,
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document');
  const byName = await session.api.get(`${base}/search`, { params: { q: 'recovery-guide' } });
  expect(byName.status()).toBe(200);
  expect((await byName.json()).items.map((item: { node_id: string }) => item.node_id)).toContain(source.id);
  await expect.poll(async () => {
    const response = await session.api.get(`${base}/nodes/${source.id}/processing`);
    expect(response.status()).toBe(200);
    const status = await response.json();
    if (status.publication_status === 'failed' || status.index_status === 'failed') throw new Error(`Document processing failed: ${status.error_code}`);
    return [status.publication_status, status.index_status];
  }, { timeout: 150_000 }).toEqual(['ready', 'ready']);
  const state = await (await session.api.get(`${base}/nodes/${source.id}/processing`)).json();
  expect(state.published_generation).toBe(state.desired_generation);
  expect(state.indexed_generation).toBe(state.desired_generation);
  const artifact = await (await session.api.get(`${base}/nodes/${state.artifact_root_id}`)).json();
  expect(artifact.kind).toBe('directory');
  for (const field of ['title', 'description', 'semantic_type', 'context', 'media_type']) expect(artifact).not.toHaveProperty(field);
  const children = await (await session.api.get(`${base}/nodes`, { params: { parent_id: artifact.id } })).json();
  const readme = children.items.find((node: { name: string }) => node.name === 'README.md');
  expect(readme).toBeDefined();
  const readmeDetails = await (await session.api.get(`${base}/nodes/${readme.id}`)).json();
  expect(readmeDetails.semantic_type).toMatch(/^[a-z]+:[a-z_]+$/);
  const original = await (await session.api.get(`${base}/nodes/${source.id}`)).json();
  for (const field of ['title', 'description', 'semantic_type', 'context']) expect(original[field]).toBe(readmeDetails[field]);
  const content = await session.api.get(`${base}/nodes/${readme.id}/content`);
  expect((await content.body()).toString('utf8')).toContain('ORBITAL-RECOVERY-7421');
  expect(await (await session.api.get(`${base}/nodes/${source.id}/content`)).body()).toEqual(bytes);
  const search = await session.api.post(`${base}/search`, { data: { query: 'ORBITAL-RECOVERY-7421' } });
  expect(search.status()).toBe(200);
  expect((await search.json()).items.map((item: { node_id: string }) => item.node_id)).toContain(source.id);
  await recordWorkflowHistory('ProcessFileParsed', `process-file/${source.id}/${state.desired_generation}`);
});

test('manual reprocessing retries admit one generation and preserve filename search during model failure', async ({ session, controls }) => {
  const base = `/v1/workspaces/${session.workspaceId}`;
  const source = await inline(session, 'retry-notes.txt', Buffer.from('Recovery notes describe durable publication and storage retry.'), session.rootId, 'text/plain');
  await expect.poll(async () => (await (await session.api.get(`${base}/nodes/${source.id}/processing`)).json()).index_status).toBe('ready');
  const before = await (await session.api.get(`${base}/nodes/${source.id}/processing`)).json();
  await recordWorkflowHistory('ProcessFileDirect', `process-file/${source.id}/${before.desired_generation}`);
  expect((await controls.put('/control/failures', { data: { generation: 100 } })).status()).toBe(200);
  try {
    const headers = { 'idempotency-key': randomUUID() };
    const first = await session.api.post(`${base}/nodes/${source.id}/processing-runs`, { headers, data: {} });
    expect(first.status()).toBe(202);
    const admission = await first.json();
    expect(BigInt(admission.generation)).toBe(BigInt(before.desired_generation) + 1n);
    const replay = await session.api.post(`${base}/nodes/${source.id}/processing-runs`, { headers, data: {} });
    expect(replay.status()).toBe(202);
    expect(await replay.json()).toEqual(admission);
    const names = await session.api.get(`${base}/search`, { params: { q: 'retry-notes' } });
    expect(names.status()).toBe(200);
    expect((await names.json()).items.map((item: { node_id: string }) => item.node_id)).toContain(source.id);
    await expect.poll(async () => (await (await session.api.get(`${base}/nodes/${source.id}/processing`)).json()).publication_status,
      { timeout: 150_000 }).toBe('failed');
    const failedNames = await session.api.get(`${base}/search`, { params: { q: 'retry-notes' } });
    expect(failedNames.status()).toBe(200);
    expect((await failedNames.json()).items.map((item: { node_id: string }) => item.node_id)).toContain(source.id);
    await recordWorkflowHistory('ProcessFileFailed', `process-file/${source.id}/${admission.generation}`, true);
  } finally { await controls.put('/control/failures', { data: {} }); }
});
