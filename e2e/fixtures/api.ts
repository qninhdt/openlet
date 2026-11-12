import { test as base, expect, type APIRequestContext } from '@playwright/test';
import { importJWK, SignJWT } from 'jose';
import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { parse } from 'yaml';

export { expect };
const config = parse(readFileSync(new URL('../openlet.test.yaml', import.meta.url), 'utf8'));
const gateway = config.services.gateway.public_url;
const wiremock = new URL(config.auth.clerk.api_url).origin;

export interface Account {
  api: APIRequestContext;
  id: string;
  workspaceId: string;
  storageId: string;
  rootId: string;
  email: string;
}
interface Identity {
  createAccount(): Promise<Account>;
  sign(subject: string, userId?: string): Promise<string>;
}

export const test = base.extend<{ account: Account }, { identity: Identity }>({
  identity: [async ({ playwright }, use) => {
    const admin = await playwright.request.newContext({ baseURL: wiremock });
    const key = JSON.parse(readFileSync(process.env.OPENLET_TEST_KEY!, 'utf8'));
    const privateKey = await importJWK(key, 'RS256');
    const contexts: APIRequestContext[] = [];
    async function sign(subject: string, userId?: string) {
      return new SignJWT(userId ? { public_metadata: { openlet_user_id: userId } } : {})
        .setProtectedHeader({ alg: 'RS256', kid: key.kid })
        .setSubject(subject).setIssuer(config.auth.clerk.issuer).setAudience(config.auth.clerk.audience)
        .setIssuedAt().setExpirationTime('1h').sign(privateKey);
    }
    async function createAccount(): Promise<Account> {
      const subject = `user_${randomUUID()}`;
      const email = `${randomUUID()}@example.test`;
      const profile = { id: subject, first_name: 'Test', last_name: 'Member', image_url: '',
        email_addresses: [{ id: randomUUID(), email_address: email, verification: { status: 'verified' } }], public_metadata: {} };
      for (const [method, path] of [['GET', `/v1/users/${subject}`], ['PATCH', `/v1/users/${subject}/metadata`]]) {
        const mapping = await admin.post('/__admin/mappings', { data: {
          request: { method, urlPath: path }, response: { status: 200, jsonBody: profile, headers: { 'Content-Type': 'application/json' } },
        } });
        expect(mapping.ok()).toBeTruthy();
      }
      const bootstrap = await playwright.request.newContext({ baseURL: gateway, extraHTTPHeaders: { Authorization: `Bearer ${await sign(subject)}` } });
      contexts.push(bootstrap);
      const response = await bootstrap.post('/v1/me:onboard', { data: {} });
      expect(response.ok(), await response.text()).toBeTruthy();
      const user = await response.json();
      const zedToken = response.headers()["x-openlet-zed-token"];
      expect(zedToken).toBeTruthy();
      const api = await playwright.request.newContext({ baseURL: gateway, extraHTTPHeaders: { Authorization: `Bearer ${await sign(subject, user.id)}`, "x-openlet-zed-token": zedToken } });
      contexts.push(api);
      await expect.poll(async () => {
        const response = await api.get('/v1/workspaces');
        expect(response.ok(), await response.text()).toBeTruthy();
        return (await response.json()).workspaces?.length ?? 0;
      }).toBe(1);
      const workspaceId = (await (await api.get('/v1/workspaces')).json()).workspaces[0].id;
      await expect.poll(async () => (await api.get(`/v1/workspaces/${workspaceId}/storages?owned_only=true`)).status()).toBe(200);
      let storage: { id: string; rootNodeId: string } | undefined;
      await expect.poll(async () => {
        const response = await api.get(`/v1/workspaces/${workspaceId}/storages?owned_only=true`);
        storage = (await response.json()).storages?.find((item: { visibility: string }) => item.visibility === 'STORAGE_VISIBILITY_PRIVATE');
        return storage !== undefined;
      }).toBe(true);
      expect(storage).toBeDefined();
      if (!storage) throw new Error('Private storage was not provisioned');
      return { api, id: user.id, workspaceId, storageId: storage.id, rootId: storage.rootNodeId, email };
    }
    try { await use({ createAccount, sign }); }
    finally {
      for (const context of contexts) await context.dispose();
      await admin.dispose();
    }
  }, { scope: 'worker' }],
  account: async ({ identity }, use) => { await use(await identity.createAccount()); },
});
