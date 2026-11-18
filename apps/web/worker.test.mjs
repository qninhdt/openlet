import assert from 'node:assert/strict';
import { test, mock } from 'node:test';
import worker from './worker.js';

test('API proxy preserves authentication, query, body and streaming response', async () => {
  const fetch = mock.method(globalThis, 'fetch', async (request) => {
    assert.equal(request.url, 'https://openlet-api.qninhdt.com/v1/messages?after=123');
    assert.equal(request.headers.get('Authorization'), 'Bearer test');
    assert.equal(request.headers.get('Host'), 'openlet-api.qninhdt.com');
    assert.equal(request.redirect, 'manual');
    assert.equal(await request.text(), '{"text":"hello"}');
    return new Response('data: hello\n\n', { headers: { 'Content-Type': 'text/event-stream' } });
  });
  try {
    const response = await worker.fetch(new Request('https://example.com/v1/messages?after=123', {
      method: 'POST', headers: { Authorization: 'Bearer test', Host: 'example.com' }, body: '{"text":"hello"}',
    }), {});
    assert.equal(response.headers.get('Cache-Control'), 'no-store');
    assert.equal(response.headers.get('Content-Type'), 'text/event-stream');
    assert.equal(await response.text(), 'data: hello\n\n');
  } finally { fetch.mock.restore(); }
});

test('SPA routes use assets and HTML is never cached', async () => {
  for (const [type, expected] of [['text/html', 'no-store'], ['text/javascript', 'public, max-age=31536000']]) {
    const response = await worker.fetch(new Request('https://example.com/app/deep/link'), {
      ASSETS: { fetch: async () => new Response('asset', { headers: { 'Content-Type': type, 'Cache-Control': 'public, max-age=31536000' } }) },
    });
    assert.equal(response.headers.get('Cache-Control'), expected);
  }
});
