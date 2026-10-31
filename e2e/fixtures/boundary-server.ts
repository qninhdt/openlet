import { generateKeyPairSync, randomUUID, sign } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { createServer, request as upstreamRequest, type IncomingMessage, type ServerResponse } from 'node:http';
import { pipeline } from 'node:stream/promises';

type User = { id: string; email: string; public_metadata: Record<string, unknown> };
type StorageFault = {
  method: string;
  contains: string;
  mode: 'pause' | 'drop-response' | 'fail';
  remaining: number;
  hits: number;
  active: number;
  release: () => void;
  released: Promise<void>;
};

const secrets = Object.fromEntries(await Promise.all(
  ['fixture_control_token', 'clerk_secret_key', 'openrouter_api_key'].map(async name =>
    [name, (await readFile(`/run/secrets/${name}`, 'utf8')).trim()]),
));
const signing = generateKeyPairSync('rsa', { modulusLength: 2048 });
const invalidSigning = generateKeyPairSync('rsa', { modulusLength: 2048 });
const jwk = { ...signing.publicKey.export({ format: 'jwk' }), kid: 'api-e2e', use: 'sig', alg: 'RS256' };
const users = new Map<string, User>();
const failures = { metadata: 0, generation: 0, embeddings: 0, rerank: 0 };
const traces: Array<{ path: string; traceparent: string; baggage: boolean }> = [];
let fault: StorageFault | undefined;

function reply(response: ServerResponse, status: number, value: unknown) {
  response.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' });
  response.end(JSON.stringify(value));
}

async function jsonBody(request: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 2 * 1024 * 1024) throw new Error('fixture request exceeds limit');
    chunks.push(Buffer.from(chunk));
  }
  const value: unknown = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('JSON object required');
  return value as Record<string, unknown>;
}

function token(subject: string, overrides: Record<string, unknown>, badSignature: boolean) {
  const now = Math.floor(Date.now() / 1000);
  const payload: Record<string, unknown> = {
    iss: 'http://boundary:8080', aud: 'openlet-e2e', sub: subject,
    iat: now, nbf: now - 1, exp: now + 3600,
    ...users.get(subject)?.public_metadata, ...overrides,
  };
  for (const key of Object.keys(payload)) if (payload[key] === null) delete payload[key];
  const encoded = [JSON.stringify({ alg: 'RS256', kid: 'api-e2e', typ: 'JWT' }), JSON.stringify(payload)]
    .map(value => Buffer.from(value).toString('base64url')).join('.');
  return `${encoded}.${sign('RSA-SHA256', Buffer.from(encoded), badSignature ? invalidSigning.privateKey : signing.privateKey).toString('base64url')}`;
}

function authenticated(request: IncomingMessage, secret: string) {
  return request.headers.authorization === `Bearer ${secret}`;
}

async function serve(request: IncomingMessage, response: ServerResponse) {
  const url = new URL(request.url ?? '/', 'http://boundary');
  if (url.pathname === '/.well-known/jwks.json') return reply(response, 200, { keys: [jwk] });
  if (url.pathname === '/live') return reply(response, 200, { ready: true });

  if (url.pathname.startsWith('/control/')) {
    if (!authenticated(request, secrets.fixture_control_token)) return reply(response, 401, { error: 'control authentication required' });
    if (request.method === 'POST' && url.pathname === '/control/users') {
      const body = await jsonBody(request);
      if (typeof body.email !== 'string') return reply(response, 400, { error: 'email required' });
      const id = typeof body.id === 'string' ? body.id : `user_${randomUUID()}`;
      const user: User = { id, email: body.email, public_metadata: { fixture_marker: id } };
      users.set(id, user);
      return reply(response, 201, user);
    }
    if (request.method === 'POST' && url.pathname === '/control/token') {
      const body = await jsonBody(request);
      if (typeof body.subject !== 'string') return reply(response, 400, { error: 'subject required' });
      const claims = body.claims && typeof body.claims === 'object' && !Array.isArray(body.claims) ? body.claims : {};
      return reply(response, 200, { token: token(body.subject, claims as Record<string, unknown>, body.bad_signature === true) });
    }
    if (request.method === 'GET' && url.pathname.startsWith('/control/users/')) {
      const user = users.get(decodeURIComponent(url.pathname.slice('/control/users/'.length)));
      return reply(response, user ? 200 : 404, user ?? { error: 'unknown identity' });
    }
    if (request.method === 'GET' && url.pathname === '/control/traces') {
      const traceId = url.searchParams.get('trace_id');
      if (!traceId || !/^[0-9a-f]{32}$/.test(traceId)) return reply(response, 400, { error: 'trace_id required' });
      return reply(response, 200, traces.filter(item => item.traceparent.split('-')[1] === traceId));
    }
    if (request.method === 'PUT' && url.pathname === '/control/failures') {
      const body = await jsonBody(request);
      for (const key of Object.keys(failures) as (keyof typeof failures)[]) {
        const count = body[key] ?? 0;
        if (!Number.isInteger(count) || Number(count) < 0 || Number(count) > 100) return reply(response, 400, { error: 'invalid failure count' });
        failures[key] = Number(count);
      }
      return reply(response, 200, failures);
    }
    if (request.method === 'PUT' && url.pathname === '/control/storage') {
      const body = await jsonBody(request);
      if (!['pause', 'drop-response', 'fail'].includes(String(body.mode)) || typeof body.method !== 'string' || typeof body.contains !== 'string') {
        return reply(response, 400, { error: 'invalid storage fault' });
      }
      const remaining = body.count ?? 1;
      if (!Number.isInteger(remaining) || Number(remaining) < 1 || Number(remaining) > 100) return reply(response, 400, { error: 'invalid fault count' });
      fault?.release();
      let release = () => {};
      const released = new Promise<void>(resolve => { release = resolve; });
      fault = { method: body.method, contains: body.contains, mode: body.mode as StorageFault['mode'], remaining: Number(remaining), hits: 0, active: 0, release, released };
      return reply(response, 200, { installed: true });
    }
    if (url.pathname === '/control/storage' && request.method === 'GET') return reply(response, 200, { hits: fault?.hits ?? 0, active: fault?.active ?? 0 });
    if (url.pathname === '/control/storage' && request.method === 'DELETE') {
      fault?.release();
      fault = undefined;
      return reply(response, 200, { released: true });
    }
    return reply(response, 404, { error: 'unknown control resource' });
  }

  if (url.pathname.startsWith('/v1/users/')) {
    if (!authenticated(request, secrets.clerk_secret_key)) return reply(response, 401, { error: 'Clerk authentication required' });
    const match = /^\/v1\/users\/([^/]+)(\/metadata)?$/.exec(url.pathname);
    const user = match && users.get(decodeURIComponent(match[1]));
    if (!user) return reply(response, 404, { error: 'unknown user' });
    if (request.method === 'PATCH' && match[2]) {
      if (failures.metadata > 0) { failures.metadata--; return reply(response, 503, { error: 'injected Clerk outage' }); }
      const body = await jsonBody(request);
      if (!body.public_metadata || typeof body.public_metadata !== 'object' || Array.isArray(body.public_metadata)) return reply(response, 400, { error: 'public_metadata required' });
      for (const [key, value] of Object.entries(body.public_metadata)) {
        if (value === null) delete user.public_metadata[key];
        else user.public_metadata[key] = value;
      }
    } else if (request.method !== 'GET' || match[2]) return reply(response, 405, { error: 'method not allowed' });
    return reply(response, 200, { ...user, email_addresses: [{ email_address: user.email, verification: { status: 'verified' } }] });
  }

  if (url.pathname.startsWith('/api/v1/')) {
    if (!authenticated(request, secrets.openrouter_api_key)) return reply(response, 401, { error: 'model authentication required' });
    const traceparent = request.headers.traceparent;
    if (typeof traceparent === 'string' && /^00-[0-9a-f]{32}-[0-9a-f]{16}-0[01]$/.test(traceparent)) {
      traces.push({ path: url.pathname, traceparent, baggage: request.headers.baggage !== undefined });
      if (traces.length > 512) traces.shift();
    }
    const body = await jsonBody(request);
    if (url.pathname.endsWith('/embeddings')) {
      if (failures.embeddings > 0) { failures.embeddings--; return reply(response, 503, { error: 'injected embedding outage' }); }
      const dimension = Number(body.dimensions ?? 8);
      if (!Number.isInteger(dimension) || dimension < 1 || dimension > 4096 || !Array.isArray(body.input)) return reply(response, 400, { error: 'invalid embedding input' });
      return reply(response, 200, { object: 'list', model: body.model, data: body.input.map((_, index) => ({ object: 'embedding', index, embedding: Array.from({ length: dimension }, (_value, i) => i === index % dimension ? 1 : 0.1) })), usage: { prompt_tokens: 1, total_tokens: 1 } });
    }
    if (url.pathname.endsWith('/rerank')) {
      if (failures.rerank > 0) { failures.rerank--; return reply(response, 503, { error: 'injected rerank outage' }); }
      if (!Array.isArray(body.documents)) return reply(response, 400, { error: 'documents required' });
      return reply(response, 200, { results: body.documents.map((_, index) => ({ index, relevance_score: 1 / (index + 1) })) });
    }
    if (url.pathname.endsWith('/chat/completions')) {
      if (failures.generation > 0) { failures.generation--; return reply(response, 503, { error: 'injected model outage' }); }
      if (!Array.isArray(body.messages)) return reply(response, 400, { error: 'messages required' });
      const serialized = body.messages.flatMap(message => typeof message.content === 'string' ? [message.content]
        : Array.isArray(message.content) ? message.content.flatMap((part: { type?: string; text?: string }) =>
          part.type === 'text' && typeof part.text === 'string' ? [part.text] : []) : []).join('\n');
      const values = /"enum"\s*:\s*(\[[^\]]+\])/.exec(serialized);
      if (!values) return reply(response, 400, { error: 'structured semantic schema required' });
      const semanticType: unknown = JSON.parse(values[1])[0];
      if (typeof semanticType !== 'string') return reply(response, 400, { error: 'semantic enum required' });
      const content = { title: 'Storage recovery guide', description: 'A guide to storage recovery and consistency.', type: semanticType, context: 'The supplied document explains recovery, durable storage, and consistency checks.' };
      return reply(response, 200, { id: randomUUID(), object: 'chat.completion', created: Math.floor(Date.now() / 1000), model: body.model, choices: [{ index: 0, finish_reason: 'stop', message: { role: 'assistant', content: JSON.stringify(content) } }], usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 } });
    }
  }
  return reply(response, 404, { error: 'unknown fixture resource' });
}

const api = createServer((request, response) => {
  serve(request, response).catch(() => {
    if (response.destroyed) return;
    if (!response.headersSent) reply(response, 400, { error: 'invalid fixture request' });
    else response.destroy();
  });
});
async function proxyStorage(request: IncomingMessage, response: ServerResponse) {
  const selected = fault && fault.remaining > 0 && fault.method === request.method && request.url?.includes(fault.contains) ? fault : undefined;
  if (selected) {
    selected.remaining--;
    selected.hits++;
    selected.active++;
    response.once('close', () => selected.active--);
    if (selected.mode === 'fail') return reply(response, 503, { error: 'injected storage outage' });
    if (selected.mode === 'pause') {
      const disconnected = new Promise<void>(resolve => response.once('close', resolve));
      await Promise.race([selected.released, disconnected]);
      if (response.destroyed) return;
    }
  }
  const upstream = upstreamRequest({ hostname: 'storage', port: 8333, method: request.method, path: request.url, headers: request.headers }, result => {
    if (selected?.mode === 'drop-response') {
      const drop = () => response.destroy();
      result.once('end', drop);
      result.once('aborted', drop);
      result.once('error', drop);
      result.resume();
    } else {
      response.writeHead(result.statusCode ?? 502, result.headers);
      pipeline(result, response).catch(() => response.destroy());
    }
  });
  upstream.setTimeout(120_000, () => upstream.destroy(new Error('storage fixture deadline')));
  upstream.on('error', () => {
    if (response.destroyed) return;
    if (!response.headersSent) reply(response, 502, { error: 'storage upstream failed' });
    else response.destroy();
  });
  response.on('close', () => upstream.destroy());
  pipeline(request, upstream).catch(() => upstream.destroy());
}

const storage = createServer((request, response) => {
  proxyStorage(request, response).catch(() => {
    if (response.destroyed) return;
    if (!response.headersSent) reply(response, 502, { error: 'storage proxy failed' });
    else response.destroy();
  });
});

api.listen(8080, '0.0.0.0');
storage.listen(8333, '0.0.0.0');
let shuttingDown = false;
for (const signal of ['SIGTERM', 'SIGINT'] as const) process.once(signal, () => {
  if (shuttingDown) return;
  shuttingDown = true;
  fault?.release();
  api.close(); storage.close(); api.closeAllConnections(); storage.closeAllConnections();
});
