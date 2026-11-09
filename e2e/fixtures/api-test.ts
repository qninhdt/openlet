import { test as base, expect, type APIRequest, type APIRequestContext } from '@playwright/test';
import { createHash, randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { control, gateway, state } from '../setup/settings.ts';

type Identity = { id: string; email: string };
export type Session = { api: APIRequestContext; userId: string; workspaceId: string; filesystemId: string; scopeId: string; personalScopeId: string; rootId: string };

export const test = base.extend<{ identity: Identity; controls: APIRequestContext; session: Session }>({
  controls: async ({ playwright }, use) => {
    const secret = (await readFile(join(state, 'secrets/fixture_control_token'), 'utf8')).trim();
    const context = await playwright.request.newContext({ baseURL: control, extraHTTPHeaders: { authorization: `Bearer ${secret}` } });
    try { await use(context); } finally { await context.dispose(); }
  },
  identity: async ({ controls }, use) => {
    const response = await controls.post('/control/users', { data: { email: `${randomUUID()}@example.test` } });
    expect(response.status()).toBe(201);
    const user = await response.json();
    expect(user.id).toEqual(expect.any(String));
    await use(user);
  },
  session: async ({ controls, identity, playwright }, use) => {
    const session = await onboard(controls, identity, playwright.request);
    try { await use(session); } finally { await session.api.dispose(); }
  },
});

export async function mint(controls: APIRequestContext, identity: Identity, claims: Record<string, unknown> = {}, badSignature = false): Promise<string> {
  const response = await controls.post('/control/token', { data: { subject: identity.id, claims, bad_signature: badSignature } });
  expect(response.status()).toBe(200);
  const body = await response.json();
  expect(body.token).toEqual(expect.any(String));
  return body.token;
}

export async function onboard(controls: APIRequestContext, identity: Identity, factory: APIRequest): Promise<Session> {
  const bootstrap = await mint(controls, identity);
  const initial = await factory.newContext({ baseURL: gateway, extraHTTPHeaders: { authorization: `Bearer ${bootstrap}` } });
  try {
    const response = await initial.put('/v1/me/onboarding');
    expect(response.status()).toBe(202);
    const admission = await response.json();
    expect(admission.user_id).toEqual(expect.any(String));
    await expect.poll(async () => {
      const status = await initial.get('/v1/me/onboarding');
      expect(status.status()).toBe(200);
      return (await status.json()).status;
    }).toBe('active');
    const refreshed = await mint(controls, identity);
    const api = await factory.newContext({ baseURL: gateway, extraHTTPHeaders: { authorization: `Bearer ${refreshed}` } });
    try {
      const listing = await api.get("/v1/workspaces");
      expect(listing.status(), await listing.text()).toBe(200);
      const initialWorkspace=(await listing.json()).items[0];
      const workspace = await api.get(`/v1/workspaces/${initialWorkspace.id}`);
      expect(workspace.status()).toBe(200);
      const resource = await workspace.json();
      expect(resource).toMatchObject({ status: 'active', shared_scope_id: expect.any(String) });
      const root = await api.get(`/v1/filesystems/${resource.filesystem_id}/scopes/${resource.shared_scope_id}/nodes:resolve`,{params:{path:'/'}});
      expect(root.status()).toBe(200);
      const members=await api.get(`/v1/workspaces/${resource.id}/members`);
      expect(members.status()).toBe(200);
      const self=(await members.json()).items.find((m:{user:{id:string}})=>m.user.id===admission.user_id);
      return { api, userId: admission.user_id, workspaceId: resource.id, filesystemId: resource.filesystem_id, scopeId: resource.shared_scope_id, personalScopeId:self.personal_scope_id, rootId: (await root.json()).id };
    } catch (error) { await api.dispose(); throw error; }
  } finally { await initial.dispose(); }
}

export async function directory(session: Session, name: string, parentId = session.rootId) {
  const response = await session.api.post(`/v1/filesystems/${session.filesystemId}/scopes/${session.scopeId}/nodes`, {
    headers: { 'idempotency-key': randomUUID() }, data: { kind: 'directory', parent_id: parentId, name },
  });
  expect(response.status()).toBe(201);
  expect(response.headers().etag).toMatch(/^"[1-9][0-9]*"$/);
  return response.json();
}

export async function inline(session: Session, name: string, bytes: Buffer, parentId = session.rootId, mediaType = 'application/octet-stream') {
  const response = await session.api.post(`/v1/filesystems/${session.filesystemId}/scopes/${session.scopeId}/nodes`, {
    headers: { 'idempotency-key': randomUUID() }, data: { kind: 'file', parent_id: parentId, name,
      content_base64: bytes.toString('base64'), media_type: mediaType },
  });
  expect(response.status()).toBe(201);
  return response.json();
}

export async function objectFile(session: Session, storage: APIRequestContext, name: string, bytes: Buffer, parentId = session.rootId, mediaType = 'application/octet-stream') {
  const base = `/v1/filesystems/${session.filesystemId}/scopes/${session.scopeId}`;
  const response = await session.api.post(`${base}/uploads`, { headers: { 'idempotency-key': randomUUID() },
    data: { parent_id: parentId, name, size_bytes: String(bytes.length), media_type: mediaType, content_md5: createHash('md5').update(bytes).digest('base64') } });
  expect(response.status()).toBe(201);
  const sessionResource = await response.json();
  expect(sessionResource.transport).toBe('single');
  expect((await storage.put(sessionResource.transfer.url, { headers: sessionResource.transfer.headers, data: bytes })).status()).toBe(200);
  const result = await session.api.put(`${base}/uploads/${sessionResource.id}/completion`, { data: {} });
  expect(result.status()).toBe(200);
  return result.json();
}

export { expect };
