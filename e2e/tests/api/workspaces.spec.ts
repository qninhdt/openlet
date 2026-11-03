import { randomUUID } from 'node:crypto';
import { test, expect, onboard, inline } from '../../fixtures/api-test.ts';
import { recordWorkflowHistory, setTemporalRunning, temporalIsHealthy } from '../../fixtures/temporal-control.ts';

test('concurrent workspace admission replays one resource and rejects changed input', async ({ session }) => {
  const key = randomUUID();
  const responses = await Promise.all(Array.from({ length: 4 }, () => session.api.post('/v1/workspaces', {
    headers: { 'idempotency-key': key }, data: { name: 'Research' },
  })));
  const ids: string[] = [];
  for (const response of responses) {
    expect([200, 202]).toContain(response.status());
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

test('ownership transfer atomically changes privileges and rejects the previous revision', async ({ session, controls, playwright }) => {
  const identity = await (await controls.post('/control/users', { data: { email: `${randomUUID()}@example.test` } })).json();
  const successor = await onboard(controls, identity, playwright.request);
  const base = `/v1/workspaces/${session.workspaceId}`;
  try {
    const invitation = await (await session.api.post(`${base}/invitations`, { data: { email: identity.email, role: 'editor' } })).json();
    expect((await successor.api.post('/v1/memberships', { data: { token: invitation.token } })).status()).toBe(201);
    const current = await session.api.get(base);
    const transferred = await session.api.patch(base, { headers: { 'if-match': current.headers().etag }, data: { owner_id: successor.userId } });
    expect(transferred.status()).toBe(200);
    expect(transferred.headers().etag).not.toBe(current.headers().etag);
    await recordWorkflowHistory('WorkspacePermissions', `workspace-permissions/${session.workspaceId}`, false, true);
    const members = await successor.api.get(`${base}/members`);
    expect(members.status()).toBe(200);
    const owners = (await members.json()).items.filter((member: { role: string }) => member.role === 'owner');
    expect(owners).toEqual([expect.objectContaining({ user: expect.objectContaining({ id: successor.userId }) })]);
    const previousOwner = await session.api.get(base);
    expect((await session.api.patch(base, { headers: { 'if-match': previousOwner.headers().etag }, data: { owner_id: session.userId } })).status()).toBe(403);
    expect((await successor.api.patch(base, { headers: { 'if-match': current.headers().etag }, data: { name: 'stale rename' } })).status()).toBe(412);
  } finally { await successor.api.dispose(); }
});

test('invitation token is returned once and current membership controls file access', async ({ session, controls, playwright }) => {
  const identity = await (await controls.post('/control/users', { data: { email: `${randomUUID()}@example.test` } })).json();
  const guest = await onboard(controls, identity, playwright.request);
  const base = `/v1/workspaces/${session.workspaceId}`;
  try {
    expect((await guest.api.get(base)).status()).toBe(404);
    const created = await session.api.post(`${base}/invitations`, { data: { email: identity.email, role: 'viewer' } });
    expect(created.status()).toBe(201);
    const invitation = await created.json();
    expect(invitation.token).toEqual(expect.any(String));
    const repeated = await session.api.post(`${base}/invitations`, { data: { email: identity.email.toUpperCase(), role: 'viewer' } });
    expect(repeated.status()).toBe(200);
    expect(await repeated.json()).toMatchObject({ id: invitation.id, status: 'pending' });
    expect(await repeated.json()).not.toHaveProperty('token');
    const joined = await guest.api.post('/v1/memberships', { data: { token: invitation.token } });
    expect(joined.status()).toBe(201);
    expect(await joined.json()).toMatchObject({ user: { id: guest.userId }, role: 'viewer' });
    expect((await guest.api.get(base)).status()).toBe(200);
    expect((await guest.api.post(`/v1/filesystems/${session.filesystemId}/nodes`, { headers: { 'idempotency-key': randomUUID() }, data: { kind: 'directory', parent_id: session.rootId, name: 'forbidden' } })).status()).toBe(403);
    const source = await inline(session, 'monitor-source.bin', Buffer.from('copy'));
    const admitted = await session.api.post(`/v1/filesystems/${session.filesystemId}/nodes`, { headers: { 'idempotency-key': randomUUID(), 'if-match': '"1"' }, data: { source_id: source.id, parent_id: session.rootId, name: 'monitor-result.bin' } });
    expect(admitted.status()).toBe(202);
    const monitor = admitted.headers().location;
    await expect.poll(async () => (await (await session.api.get(monitor)).json()).status).toBe('succeeded');
    expect((await guest.api.get(monitor, { headers: { 'x-workspace-role': 'owner' } })).status()).toBe(404);
    const current = await session.api.get(base);
    const removed = await session.api.delete(`${base}/members/${guest.userId}`, { headers: { 'if-match': current.headers().etag } });
    expect(removed.status()).toBe(204);
    expect((await guest.api.get(`/v1/filesystems/${session.filesystemId}/nodes/${session.rootId}`)).status()).toBe(403);
    expect((await guest.api.get(monitor)).status()).toBe(403);
    const replay = await guest.api.post('/v1/memberships', { data: { token: invitation.token } });
    expect(replay.status()).toBe(409);
  } finally { await guest.api.dispose(); }
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
  expect([200, 202]).toContain(admitted.status());
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
  const upload = `/v1/filesystems/${session.filesystemId}/uploads/${randomUUID()}`;
  try {
    const invitation = await (await session.api.post(`${base}/invitations`, { data: { email: identity.email, role: 'viewer' } })).json();
    expect((await guest.api.post('/v1/memberships', { data: { token: invitation.token } })).status()).toBe(201);
    expect((await guest.api.get(upload)).status()).toBe(403);
    const current = await session.api.get(base);
    await setTemporalRunning(false);
    try {
      const change = await session.api.patch(`${base}/members/${guest.userId}`, {
        headers: { 'if-match': current.headers().etag }, data: { role: 'editor' },
      });
      expect(change.status()).toBe(503);
      const members = await (await session.api.get(`${base}/members`)).json();
      expect(members.items).toContainEqual(expect.objectContaining({ user: expect.objectContaining({ id: guest.userId }), role: 'viewer' }));
      expect((await guest.api.get(upload)).status()).toBe(403);
    } finally { await setTemporalRunning(true); }
    await expect.poll(temporalIsHealthy, { timeout: 90_000 }).toBe(true);
    const retried = await session.api.patch(`${base}/members/${guest.userId}`, {
      headers: { 'if-match': current.headers().etag }, data: { role: 'editor' },
    });
    expect(retried.status()).toBe(204);
    await expect.poll(async () => (await guest.api.get(upload)).status()).toBe(404);
    const refreshed = await session.api.get(base);
    expect(refreshed.headers().etag).not.toBe(current.headers().etag);
  } finally { await guest.api.dispose(); }
});
