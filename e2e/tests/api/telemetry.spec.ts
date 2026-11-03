import { randomBytes, randomUUID } from 'node:crypto';
import { test, expect } from '../../fixtures/api-test.ts';

test('HTTP and Temporal preserve trace context through Go and Python without baggage', async ({ session, controls }) => {
  const traceId = randomBytes(16).toString('hex');
  const traceparent = `00-${traceId}-${randomBytes(8).toString('hex')}-01`;
  const base = `/v1/filesystems/${session.filesystemId}`;
  const response = await session.api.post(`${base}/nodes`, {
    headers: { traceparent, baggage: 'private=must-not-propagate', 'idempotency-key': randomUUID() },
    data: { kind: 'file', parent_id: session.rootId, name: 'trace-context.txt', media_type: 'text/plain',
      content_base64: Buffer.from('Recovery preserves durable data through retries.').toString('base64') },
  });
  expect(response.status()).toBe(201);
  const source = await response.json();
  await expect.poll(async () => {
    const result = await session.api.get(`${base}/nodes/${source.id}/processing`);
    expect(result.status()).toBe(200);
    return (await result.json()).publication_status;
  }).toBe('ready');
  await expect.poll(async () => {
    const observed = await controls.get('/control/traces', { params: { trace_id: traceId } });
    expect(observed.status()).toBe(200);
    const requests: Array<{ path: string; traceparent: string; baggage: boolean }> = await observed.json();
    for (const request of requests) {
      expect(request.traceparent.split('-')[1]).toBe(traceId);
      expect(request.baggage).toBe(false);
    }
    return [...new Set(requests.map(request => request.path))].sort();
  }).toEqual(['/api/v1/chat/completions', '/api/v1/embeddings']);
});
