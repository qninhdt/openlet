import { randomUUID } from 'node:crypto';
import { request as rawRequest } from 'node:http';
import { test, expect, mint } from '../../fixtures/api-test.ts';
import { gateway } from '../../setup/settings.ts';

test.describe('gateway baseline', () => {
  test('rejects missing, invalid, expired and incorrectly scoped JWTs', async ({ request, controls, identity }) => {
    expect((await request.get('/v1/me')).status()).toBe(401);
    for (const [claims, status] of [[{ exp: 1 }, 401], [{ iss: 'https://untrusted.example.test' }, 401], [{ aud: 'another-product' }, 403]] as const) {
      const jwt = await mint(controls, identity, claims);
      expect((await request.get('/v1/me', { headers: { authorization: `Bearer ${jwt}` } })).status()).toBe(status);
    }
    const jwt = await mint(controls, identity, {}, true);
    expect((await request.get('/v1/me', { headers: { authorization: `Bearer ${jwt}` } })).status()).toBe(401);
  });

  test('strips forged and duplicate trusted headers before checking the verified identity', async ({ controls, identity }) => {
    const jwt = await mint(controls, identity);
    const status = await new Promise<number>((resolve, reject) => {
      const request = rawRequest(`${gateway}/v1/me`, { headers: [
        'Host', new URL(gateway).host,
        'Authorization', `Bearer ${jwt}`,
        'X-Openlet-User-ID', randomUUID(), 'X-Openlet-User-ID', randomUUID(),
        'X-Clerk-Sub', 'forged', 'X-Gateway-Token', 'forged', 'X-Service-Token', 'forged',
      ] }, response => { response.resume(); response.on('end', () => resolve(response.statusCode ?? 0)); });
      request.setTimeout(5000, () => request.destroy(new Error('gateway deadline')));
      request.on('error', reject); request.end();
    });
    expect(status).toBe(403);
  });

  test('routes verified requests to real Account and Workspace without exposing internal resources', async ({ request, controls, identity }) => {
    const jwt = await mint(controls, identity, { openlet_user_id: randomUUID() });
    const headers = { authorization: `Bearer ${jwt}` };
    const me = await request.get('/v1/me', { headers });
    expect(me.status()).toBe(404);
    const workspaces = await request.get('/v1/workspaces', { headers });
    expect(workspaces.status()).toBe(200);
    expect(await workspaces.json()).toMatchObject({ items: [] });
    for (const path of ['/internal/v1/users', '/internal/v1/quota-buckets', '/ready']) {
      expect((await request.get(path, { headers })).status()).toBe(404);
    }
  });

  test('bounds gateway request bursts', async ({ request, controls, identity }) => {
    const jwt = await mint(controls, identity, { openlet_user_id: randomUUID() });
    const statuses = await Promise.all(Array.from({ length: 400 }, async () => {
      const response = await request.get('/v1/me', { headers: { authorization: `Bearer ${jwt}` } });
      const status = response.status(); await response.dispose(); return status;
    }));
    expect(statuses).toContain(429);
    expect(statuses.every(status => status === 404 || status === 429)).toBe(true);
    await expect.poll(async () => (await request.get('/v1/me', { headers: { authorization: `Bearer ${jwt}` } })).status()).toBe(404);
  });
});
