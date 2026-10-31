import { test, expect } from '@playwright/test';
import { isDeepStrictEqual } from 'node:util';

test('sandbox Clerk publishes only owned metadata and a newly minted JWT reaches the real gateway', async ({ playwright }) => {
  const gateway = process.env.OPENLET_SANDBOX_GATEWAY;
  const key = process.env.CLERK_SECRET_KEY;
  const session = process.env.CLERK_SESSION_ID;
  if (!gateway || !key?.startsWith('sk_test_') || !session?.startsWith('sess_')) {
    throw new Error('NOT RUN: set OPENLET_SANDBOX_GATEWAY, a Clerk sk_test_ secret and CLERK_SESSION_ID for a dedicated development session');
  }
  const endpoint = new URL(gateway);
  if (endpoint.protocol !== 'https:' && !(endpoint.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(endpoint.hostname))) throw new Error('Sandbox gateway requires HTTPS or loopback');
  if (endpoint.username || endpoint.password || endpoint.search || endpoint.hash) throw new Error('Invalid sandbox gateway URL');
  const clerk = await playwright.request.newContext({ baseURL: 'https://api.clerk.com', extraHTTPHeaders: { authorization: `Bearer ${key}` } });
  const api = await playwright.request.newContext({ baseURL: endpoint.origin });
  try {
    const selected = await clerk.get(`/v1/sessions/${encodeURIComponent(session)}`);
    expect(selected.status()).toBe(200);
    const userId = (await selected.json()).user_id;
    expect(typeof userId).toBe('string');
    const before = await clerk.get(`/v1/users/${encodeURIComponent(userId)}`);
    expect(before.status()).toBe(200);
    const previous = (await before.json()).public_metadata;
    const bootstrap = await clerk.post(`/v1/sessions/${encodeURIComponent(session)}/tokens`, { data: {} });
    expect(bootstrap.status()).toBe(200);
    const token = (await bootstrap.json()).jwt;
    expect(typeof token).toBe('string');
    const accepted = await api.put('/v1/me/onboarding', { headers: { authorization: `Bearer ${token}` } });
    expect([200,202]).toContain(accepted.status());
    const receipt = await accepted.json();
    await expect.poll(async () => {
      const status = await api.get('/v1/me/onboarding', { headers: { authorization: `Bearer ${token}` } });
      expect(status.status()).toBe(200);
      return (await status.json()).status;
    }).toBe('active');
    const ready = await (await api.get('/v1/me/onboarding', { headers: { authorization: `Bearer ${token}` } })).json();
    expect(ready.workspace_id).toEqual(expect.any(String));
    const after = await clerk.get(`/v1/users/${encodeURIComponent(userId)}`);
    expect(after.status()).toBe(200);
    const published = (await after.json()).public_metadata;
    expect(published.openlet_user_id).toBe(receipt.user_id);
    const unowned = (metadata: Record<string, unknown>) => Object.fromEntries(Object.entries(metadata).filter(([name]) => name !== 'openlet_user_id').sort(([a], [b]) => a.localeCompare(b)));
    expect(isDeepStrictEqual(unowned(published), unowned(previous))).toBe(true);
    const refreshed = await clerk.post(`/v1/sessions/${encodeURIComponent(session)}/tokens`, { data: {} });
    expect(refreshed.status()).toBe(200);
    const freshToken = (await refreshed.json()).jwt;
    const claims = JSON.parse(Buffer.from(freshToken.split('.')[1], 'base64url').toString('utf8'));
    expect(claims.openlet_user_id).toBe(receipt.user_id);
    expect((await api.get('/v1/me', { headers: { authorization: `Bearer ${freshToken}` } })).status()).toBe(200);
    expect((await api.get(`/v1/workspaces/${ready.workspace_id}`, { headers: { authorization: `Bearer ${freshToken}` } })).status()).toBe(200);
  } finally { await clerk.dispose(); await api.dispose(); }
});
