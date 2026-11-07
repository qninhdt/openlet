import { randomUUID } from 'node:crypto';
import { test, expect, onboard } from '../../fixtures/api-test.ts';
import { recordLatestHistory, recordWorkflowHistory, setTemporalRunning, temporalIsHealthy } from '../../fixtures/temporal-control.ts';

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
    expect(membership).toMatchObject({ account: { id: guest.accountId }, role: 'member' });
    expect((await guest.api.get(`${shared}/nodes/${session.rootId}`)).status()).toBe(200);
    const personal=`/v1/filesystems/${session.filesystemId}/scopes/${membership.personal_scope_id}`;
    const root=await guest.api.get(`${personal}/nodes:resolve`,{params:{path:'/'}});
    expect(root.status()).toBe(200);
    expect((await session.api.get(`${personal}/nodes:resolve`,{params:{path:'/'}})).status()).toBe(403);
    const file=await guest.api.post(`${personal}/nodes`,{headers:{'idempotency-key':randomUUID()},data:{kind:'file',parent_id:(await root.json()).id,name:'private.txt',content_base64:Buffer.from('private').toString('base64')}});
    expect(file.status()).toBe(201);
    const fileId=(await file.json()).id;
    const access = `${base}/scopes/${membership.personal_scope_id}/access/${session.accountId}`;
    expect((await session.api.put(access, { data: { role: 'viewer' } })).status()).toBe(403);
    expect((await guest.api.put(access, { data: { role: 'viewer' } })).status()).toBe(204);
    expect(await (await session.api.get(`${personal}/nodes/${fileId}/content`)).body()).toEqual(Buffer.from('private'));
    expect((await session.api.post(`${personal}/nodes`, { headers: { 'idempotency-key': randomUUID() },
      data: { kind: 'directory', parent_id: (await root.json()).id, name: 'forbidden' } })).status()).toBe(403);
    expect((await guest.api.delete(access, { data: { role: 'viewer' } })).status()).toBe(204);
    expect((await session.api.get(`${personal}/nodes/${fileId}/content`)).status()).toBe(403);
    expect((await session.api.patch(`${base}/members/${session.accountId}`,{data:{role:'member'}})).status()).toBe(403);
    expect((await session.api.delete(`${base}/members/${guest.accountId}`)).status()).toBe(204);
    expect((await guest.api.get(`${shared}/nodes/${session.rootId}`)).status()).toBe(403);
    expect((await guest.api.get(`${personal}/nodes/${fileId}`)).status()).toBe(403);
    expect((await guest.api.post('/v1/memberships',{data:{token}})).status()).toBe(409);
    expect((await session.api.post(`${base}/members`,{data:{account_id:guest.accountId,role:'member'}})).status()).toBe(201);
    const members=await (await session.api.get(`${base}/members`)).json();
    expect(members.items.find((m:{account:{id:string}})=>m.account.id===guest.accountId).personal_scope_id).toBe(membership.personal_scope_id);
    expect(await (await guest.api.get(`${personal}/nodes/${fileId}/content`)).body()).toEqual(Buffer.from('private'));
    await recordWorkflowHistory('WorkspaceChanges',`workspace-changes/${session.workspaceId}`,false,true);
  } finally { await guest.api.dispose(); }
});

test('owned accounts have independent resource membership',async({session})=>{
 const created=await session.api.post('/v1/accounts',{data:{display_name:'Independent account'}});
 expect(created.status()).toBe(201);
 const account=await created.json();
 expect(account).toMatchObject({type:'agent',owner_id:session.accountId});
 await recordLatestHistory('AccountChanges', 'AccountChanges');
 expect((await session.api.patch(`/v1/accounts/${account.id}`,{data:{display_name:'Renamed'}})).status()).toBe(200);
 const base=`/v1/workspaces/${session.workspaceId}`;
 expect((await session.api.post(`${base}/members`,{data:{account_id:account.id,role:'member'}})).status()).toBe(201);
 const members=await (await session.api.get(`${base}/members`)).json();
 const member=members.items.find((m:{account:{id:string}})=>m.account.id===account.id);
 expect(member.role).toBe('member');
 expect((await session.api.get(`/v1/filesystems/${session.filesystemId}/scopes/${member.personal_scope_id}/nodes:resolve`,{params:{path:'/'}})).status()).toBe(403);
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
      const change = await session.api.patch(`${base}/members/${guest.accountId}`, {
        data: { role: 'admin' },
      });
      expect(change.status()).toBe(503);
      const members = await (await session.api.get(`${base}/members`)).json();
      expect(members.items).toContainEqual(expect.objectContaining({ account: expect.objectContaining({ id: guest.accountId }), role: 'member' }));
      expect((await guest.api.get(upload)).status()).toBe(403);
    } finally { await setTemporalRunning(true); }
    await expect.poll(temporalIsHealthy, { timeout: 90_000 }).toBe(true);
    const retried = await session.api.patch(`${base}/members/${guest.accountId}`, {
      data: { role: 'admin' },
    });
    expect(retried.status()).toBe(204);
    await expect.poll(async () => (await guest.api.get(upload)).status()).toBe(200);
    const refreshed = await session.api.get(base);
    expect(refreshed.headers().etag).toBeUndefined();
  } finally { await guest.api.dispose(); }
});
