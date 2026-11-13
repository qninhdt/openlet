import { test, expect } from '../../fixtures/api.js';
import { randomUUID } from 'node:crypto';

test('gateway verifies JWT, strips actor headers and hides internal RPCs', async ({
  request,
  account,
}) => {
  expect((await request.get('/v1/workspaces')).status()).toBe(401);
  expect(
    (
      await request.get('/v1/workspaces', { headers: { Authorization: 'Bearer invalid' } })
    ).status(),
  ).toBe(401);
  const me = await account.api.get('/v1/me', {
    headers: {
      'x-openlet-user-id': randomUUID(),
      'x-openlet-agent-id': randomUUID(),
      'x-openlet-clerk-subject': 'spoofed',
    },
  });
  expect(me.ok(), await me.text()).toBeTruthy();
  expect((await me.json()).id).toBe(account.id);
  const invalid = await account.api.get('/v1/workspaces/not-a-uuid');
  expect(invalid.status()).toBe(400);
  expect(await invalid.json()).toMatchObject({ code: 3 });
  const internal = await account.api.post(
    '/openlet.platform.v1.PlatformInternalService/CheckWorkspaceActive',
    { data: { workspaceId: account.workspaceId } },
  );
  expect(internal.status()).toBeGreaterThanOrEqual(400);
});
