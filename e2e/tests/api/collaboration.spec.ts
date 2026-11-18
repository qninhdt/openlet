import { randomUUID } from 'node:crypto';
import { test, expect } from '../../fixtures/api.js';

test('invitation, storage grant, revoke and workspace deletion', async ({ account, identity }) => {
  const guest = await identity.createAccount();
  const workspace = `/v1/workspaces/${account.workspaceId}`;
  const storage = `${workspace}/storages/${account.storageId}`;
  expect((await guest.api.get(storage)).status()).toBe(403);
  const invite = await account.api.post(`${workspace}/invitations`, {
    data: { email: guest.email, requestId: randomUUID() },
  });
  expect(invite.ok(), await invite.text()).toBeTruthy();
  const { token } = await invite.json();
  const accepted = await guest.api.post('/v1/invitations:accept', { data: { token } });
  expect(accepted.ok(), await accepted.text()).toBeTruthy();
  expect((await accepted.json()).workspaceId).toBe(account.workspaceId);
  await expect.poll(async () => (await guest.api.get(workspace)).status()).toBe(200);
  const third = await identity.createAccount();
  const overflow = await account.api.post(`${workspace}/invitations`, {
    data: { email: third.email, requestId: randomUUID() },
  });
  expect(overflow.ok(), await overflow.text()).toBeTruthy();
  const overflowToken = (await overflow.json()).token;
  const overLimit = await third.api.post('/v1/invitations:accept', {
    data: { token: overflowToken },
  });
  expect(overLimit.status(), await overLimit.text()).toBe(429);
  await expect
    .poll(async () => {
      const response = await guest.api.get(`${workspace}/storages?owned_only=true`);
      expect(response.ok(), await response.text()).toBeTruthy();
      return (await response.json()).storages?.length ?? 0;
    })
    .toBeGreaterThan(0);
  expect((await guest.api.get(storage)).status()).toBe(403);
  const granted = await account.api.post(`${storage}:setAccess`, {
    data: { actor: { userId: guest.id }, role: 'STORAGE_ROLE_VIEWER' },
  });
  expect(granted.ok(), await granted.text()).toBeTruthy();
  await expect.poll(async () => (await guest.api.get(storage)).status()).toBe(200);
  const forbidden = await guest.api.post(`${storage}/nodes`, {
    data: {
      parent: { nodeId: account.rootId },
      name: 'denied',
      directory: {},
      requestId: randomUUID(),
    },
  });
  expect(forbidden.status()).toBe(403);
  expect(
    (
      await account.api.post(`${storage}:revokeAccess`, { data: { actor: { userId: guest.id } } })
    ).ok(),
  ).toBeTruthy();
  await expect.poll(async () => (await guest.api.get(storage)).status()).toBe(403);
  const removed = await account.api.delete(`${workspace}/members/${guest.id}`);
  expect(removed.ok(), await removed.text()).toBeTruthy();
  await expect.poll(async () => (await guest.api.get(workspace)).status()).toBe(403);
  await expect
    .poll(async () =>
      (await guest.api.post('/v1/invitations:accept', { data: { token } })).status(),
    )
    .toBe(400);
  await expect.poll(async () => (await guest.api.get(workspace)).status()).toBe(403);
  const admitted = await third.api.post('/v1/invitations:accept', {
    data: { token: overflowToken },
  });
  expect(admitted.ok(), await admitted.text()).toBeTruthy();
  expect((await account.api.delete(workspace)).ok()).toBeTruthy();
  await expect
    .poll(async () => (await account.api.get(workspace)).status(), { timeout: 30_000 })
    .toBe(403);
});

test('authenticated workspace creation, validation and receipt replay', async ({
  account,
  identity,
}) => {
  const data = { name: 'Second workspace', requestId: randomUUID() };
  const created = await account.api.post('/v1/workspaces', { data });
  expect(created.ok(), await created.text()).toBeTruthy();
  const workspace = await created.json();
  expect(workspace.name).toBe(data.name);
  const replay = await account.api.post('/v1/workspaces', { data });
  expect(replay.ok(), await replay.text()).toBeTruthy();
  expect((await replay.json()).id).toBe(workspace.id);
  const headers = { 'x-openlet-zed-token': created.headers()['x-openlet-zed-token'] };
  const members = await account.api.get(`/v1/workspaces/${workspace.id}/members`, { headers });
  expect(members.ok(), await members.text()).toBeTruthy();
  expect((await members.json()).members[0]).toMatchObject({
    user: { id: account.id },
    role: 'WORKSPACE_ROLE_OWNER',
  });
  const guest = await identity.createAccount();
  expect((await guest.api.get(`/v1/workspaces/${workspace.id}`)).status()).toBe(403);
  expect(
    (
      await account.api.post('/v1/workspaces', {
        data: { ...data, name: '', requestId: randomUUID() },
      })
    ).status(),
  ).toBe(400);
  expect(
    (await account.api.delete(`/v1/workspaces/${workspace.id}`, { headers })).ok(),
  ).toBeTruthy();
});
