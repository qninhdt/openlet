import { randomUUID } from 'node:crypto';
import { test, expect, onboard } from '../../fixtures/api-test.ts';
import { recordLatestHistory, recordWorkflowHistory, setTemporalRunning, temporalIsHealthy } from '../../fixtures/temporal-control.ts';

test('scope discovery returns current permitted roots through native storage', async ({ session }) => {
  const path = `/v1/workspaces/${session.workspaceId}/scopes`;
  const response = await session.api.get(path);
  expect(response.status(), await response.text()).toBe(200);
  const result = await response.json();
  expect(result).toMatchObject({ workspace_id: session.workspaceId, filesystem_id: session.filesystemId,
    subject: { kind: 'user', id: session.userId }, next_cursor: null });
  expect(result.items).toHaveLength(2);
  expect(result.items.find((item: { id: string }) => item.id === session.scopeId)).toMatchObject({
    root_id: session.rootId, kind: 'shared', read_metadata: true, read_content: true, write: true,
  });
  const personalRoot = await session.api.get(`/v1/filesystems/${session.filesystemId}/scopes/${session.personalScopeId}/nodes:resolve`, { params: { path: '/' } });
  expect(personalRoot.status()).toBe(200);
  expect(result.items.find((item: { id: string }) => item.id === session.personalScopeId)).toMatchObject({
    root_id: (await personalRoot.json()).id, kind: 'personal', owner: { id: session.userId }, write: true,
  });
  const ids: string[] = [];
  let cursor: string | undefined;
  for (let index = 0; index < 3; index++) {
    const page = await session.api.get(path, { params: { limit: '1', ...(cursor ? { cursor } : {}) } });
    expect(page.status(), await page.text()).toBe(200);
    const body = await page.json();
    ids.push(...body.items.map((item: { id: string }) => item.id));
    if (!body.next_cursor) break;
    expect(body.next_cursor).not.toBe(cursor);
    cursor = body.next_cursor;
  }
  expect(ids.sort()).toEqual([session.scopeId, session.personalScopeId].sort());
  expect((await session.api.get(path, { params: { user_id: randomUUID() } })).status()).toBe(400);
  expect((await session.api.get(path, { params: { leta_id: randomUUID() } })).status()).toBe(403);
  expect((await session.api.get(`/v1/workspaces/${randomUUID()}/scopes`)).status()).toBe(404);
});

test('concurrent workspace admission replays one resource and rejects changed input', async ({ session }) => {
  const key = randomUUID();
  const responses = await Promise.all(Array.from({ length: 4 }, () => session.api.post('/v1/workspaces', {
    headers: { 'idempotency-key': key }, data: { name: 'Research' },
  })));
  const ids: string[] = [];
  for (const response of responses) {
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(response.headers().location).toBe(`/v1/workspaces/${body.id}`);
    ids.push(body.id);
  }
  expect(new Set(ids).size).toBe(1);
  const conflict = await session.api.post('/v1/workspaces', { headers: { 'idempotency-key': key }, data: { name: 'Different' } });
  expect(conflict.status()).toBe(409);
  expect(conflict.headers()['content-type']).toContain('application/problem+json');
  expect(await conflict.json()).toMatchObject({ status: 409, code: expect.any(String) });
  await expect.poll(async () => (await (await session.api.get(`/v1/workspaces/${ids[0]}`)).json()).status).toBe('active');
  const workspaces = await session.api.get('/v1/workspaces');
  expect((await workspaces.json()).items.map((item: { id: string }) => item.id).sort()).toEqual([session.workspaceId, ids[0]].sort());
});

test('workspace membership shares one scope and preserves private storage across leave and rejoin', async ({ session, controls, playwright }) => {
  const identity = await (await controls.post('/control/users', { data: { email: `${randomUUID()}@example.test` } })).json();
  const guest = await onboard(controls, identity, playwright.request);
  const base = `/v1/workspaces/${session.workspaceId}`;
  const shared = `/v1/filesystems/${session.filesystemId}/scopes/${session.scopeId}`;
  try {
    const invitation = await session.api.post(`${base}/invitations`, { data: { email: identity.email, role: 'member' } });
    expect(invitation.status()).toBe(201);
    const token = (await invitation.json()).token;
    const repeated = await session.api.post(`${base}/invitations`, { data: { email: identity.email.toUpperCase(), role: 'member' } });
    expect(repeated.status()).toBe(200);
    expect(await repeated.json()).not.toHaveProperty('token');
    const joined = await guest.api.post('/v1/memberships', { data: { token } });
    expect(joined.status()).toBe(201);
    const membership=await joined.json();
    expect(membership).toMatchObject({ user: { id: guest.userId }, role: 'member' });
    expect((await guest.api.get(`${shared}/nodes/${session.rootId}`)).status()).toBe(200);
    const personal=`/v1/filesystems/${session.filesystemId}/scopes/${membership.personal_scope_id}`;
    const root=await guest.api.get(`${personal}/nodes:resolve`,{params:{path:'/'}});
    expect(root.status()).toBe(200);
    expect((await session.api.get(`${personal}/nodes:resolve`,{params:{path:'/'}})).status()).toBe(403);
    const file=await guest.api.post(`${personal}/nodes`,{headers:{'idempotency-key':randomUUID()},data:{kind:'file',parent_id:(await root.json()).id,name:'private.txt',content_base64:Buffer.from('private').toString('base64')}});
    expect(file.status()).toBe(201);
    const fileId=(await file.json()).id;
    const access = `${base}/scopes/${membership.personal_scope_id}/access/${session.userId}`;
    expect((await session.api.put(access, { data: { role: 'viewer' } })).status()).toBe(403);
    expect((await guest.api.put(access, { data: { role: 'viewer' } })).status()).toBe(204);
    expect(await (await session.api.get(`${personal}/nodes/${fileId}/content`)).body()).toEqual(Buffer.from('private'));
    expect((await session.api.post(`${personal}/nodes`, { headers: { 'idempotency-key': randomUUID() },
      data: { kind: 'directory', parent_id: (await root.json()).id, name: 'forbidden' } })).status()).toBe(403);
    expect((await guest.api.delete(access, { data: { role: 'viewer' } })).status()).toBe(204);
    expect((await session.api.get(`${personal}/nodes/${fileId}/content`)).status()).toBe(403);
    expect((await session.api.patch(`${base}/members/${session.userId}`,{data:{role:'member'}})).status()).toBe(403);
    expect((await session.api.delete(`${base}/members/${guest.userId}`)).status()).toBe(204);
    expect((await guest.api.get(`${shared}/nodes/${session.rootId}`)).status()).toBe(403);
    expect((await guest.api.get(`${personal}/nodes/${fileId}`)).status()).toBe(403);
    expect((await guest.api.post('/v1/memberships',{data:{token}})).status()).toBe(409);
    expect((await session.api.post(`${base}/members`,{data:{user_id:guest.userId,role:'member'}})).status()).toBe(201);
    const members=await (await session.api.get(`${base}/members`)).json();
    expect(members.items.find((m:{user:{id:string}})=>m.user.id===guest.userId).personal_scope_id).toBe(membership.personal_scope_id);
    expect(await (await guest.api.get(`${personal}/nodes/${fileId}/content`)).body()).toEqual(Buffer.from('private'));
    await recordWorkflowHistory('WorkspaceChanges',`workspace-changes/${session.workspaceId}`,false,true);
  } finally { await guest.api.dispose(); }
});

test('managed account endpoints are removed', async ({ session }) => {
 expect((await session.api.post('/v1/accounts',{data:{display_name:'Removed'}})).status()).toBe(404);
 expect((await session.api.get(`/v1/accounts/${session.userId}`)).status()).toBe(404);
 expect((await session.api.patch(`/v1/accounts/${session.userId}`,{data:{display_name:'Removed'}})).status()).toBe(404);
});

test('Workspace admission requires Temporal before changing canonical state', async ({ session }) => {
  const key = randomUUID();
  await setTemporalRunning(false);
  try {
    const rejected = await session.api.post('/v1/workspaces', { headers: { 'idempotency-key': key }, data: { name: 'Retry creation' } });
    expect(rejected.status()).toBe(503);
    const workspaces = await session.api.get('/v1/workspaces');
    expect((await workspaces.json()).items.map((item: { id: string }) => item.id)).toEqual([session.workspaceId]);
  } finally { await setTemporalRunning(true); }
  await expect.poll(temporalIsHealthy, { timeout: 90_000 }).toBe(true);
  const admitted = await session.api.post('/v1/workspaces', { headers: { 'idempotency-key': key }, data: { name: 'Retry creation' } });
  expect(admitted.status()).toBe(200);
  const { id } = await admitted.json();
  await expect.poll(async () => (await (await session.api.get(`/v1/workspaces/${id}`)).json()).status).toBe('active');
  const replay = await session.api.post('/v1/workspaces', { headers: { 'idempotency-key': key }, data: { name: 'Retry creation' } });
  expect(replay.status()).toBe(200);
  expect(await replay.json()).toMatchObject({ id, status: 'active' });
  const workspaces = await session.api.get('/v1/workspaces');
  expect((await workspaces.json()).items.map((item: { id: string }) => item.id).sort()).toEqual([session.workspaceId, id].sort());
});

test('a Temporal outage prevents role mutation and retry updates only its member', async ({ session, controls, playwright }) => {
  const identity = await (await controls.post('/control/users', { data: { email: `${randomUUID()}@example.test` } })).json();
  const guest = await onboard(controls, identity, playwright.request);
  const base = `/v1/workspaces/${session.workspaceId}`;
  const upload = `/v1/workspaces/${session.workspaceId}/invitations`;
  try {
    const invitation = await (await session.api.post(`${base}/invitations`, { data: { email: identity.email, role: 'member' } })).json();
    expect((await guest.api.post('/v1/memberships', { data: { token: invitation.token } })).status()).toBe(201);
    expect((await guest.api.get(upload)).status()).toBe(403);
    await setTemporalRunning(false);
    try {
      const change = await session.api.patch(`${base}/members/${guest.userId}`, {
        data: { role: 'admin' },
      });
      expect(change.status()).toBe(503);
      const members = await (await session.api.get(`${base}/members`)).json();
      expect(members.items).toContainEqual(expect.objectContaining({ user: expect.objectContaining({ id: guest.userId }), role: 'member' }));
      expect((await guest.api.get(upload)).status()).toBe(403);
    } finally { await setTemporalRunning(true); }
    await expect.poll(temporalIsHealthy, { timeout: 90_000 }).toBe(true);
    const retried = await session.api.patch(`${base}/members/${guest.userId}`, {
      data: { role: 'admin' },
    });
    expect(retried.status()).toBe(204);
    await expect.poll(async () => (await guest.api.get(upload)).status()).toBe(200);
    const refreshed = await session.api.get(base);
    expect(refreshed.headers().etag).toBeUndefined();
  } finally { await guest.api.dispose(); }
});
