import { test, expect, mint } from '../../fixtures/api-test.ts';

test('onboarding uses natural identity and publishes the initial workspace into a refreshed session', async ({ request, controls, identity }) => {
  const bootstrap = await mint(controls, identity);
  const headers = { authorization: `Bearer ${bootstrap}` };
  const admitted = await request.put('/v1/me/onboarding', { headers });
  expect(admitted.status()).toBe(202);
  expect(admitted.headers().location).toBe('/v1/me/onboarding');
  const receipt = await admitted.json();
  expect(receipt).toMatchObject({ status: 'pending', user_id: expect.any(String) });
  const repeated = await request.put('/v1/me/onboarding', { headers });
  expect([200, 202]).toContain(repeated.status());
  expect(await repeated.json()).toMatchObject({ user_id: receipt.user_id });
  await expect.poll(async () => {
    const response = await request.get('/v1/me/onboarding', { headers });
    expect(response.status()).toBe(200);
    return (await response.json()).status;
  }).toBe('active');

  const clerk = await controls.get(`/control/users/${identity.id}`);
  expect((await clerk.json()).public_metadata).toMatchObject({ fixture_marker: identity.id, openlet_user_id: receipt.user_id });
  const refreshed = await mint(controls, identity);
  const authenticated = { authorization: `Bearer ${refreshed}` };
  const me = await request.get('/v1/me', { headers: authenticated });
  expect(me.status()).toBe(200);
  expect(await me.json()).toMatchObject({ id: receipt.user_id });
  const workspaces = await request.get('/v1/workspaces', { headers: authenticated });
  expect(workspaces.status()).toBe(200);
  const initialWorkspaces = (await workspaces.json()).items;
  expect(initialWorkspaces).toEqual([expect.objectContaining({ status: 'active' })]);
  expect((await request.delete(`/v1/workspaces/${initialWorkspaces[0].id}`, { headers: authenticated })).status()).toBe(204);
  const completed = await request.put('/v1/me/onboarding', { headers });
  expect(completed.status()).toBe(200);
  expect(await completed.json()).toMatchObject({ user_id: receipt.user_id, status: 'active' });
  expect((await (await request.get('/v1/workspaces', { headers: authenticated })).json()).items).toEqual([]);
});

test('Clerk metadata failure retries onboarding without duplicating the initial workspace', async ({ request, controls, identity }) => {
  expect((await controls.put('/control/failures', { data: { metadata: 2 } })).status()).toBe(200);
  try {
    const bootstrap = await mint(controls, identity);
    const headers = { authorization: `Bearer ${bootstrap}` };
    const admitted = await request.put('/v1/me/onboarding', { headers });
    expect(admitted.status()).toBe(202);
    const initial = await admitted.json();
    await expect.poll(async () => (await (await request.get('/v1/me/onboarding', { headers })).json()).status).toBe('active');

      const repeated = await request.put('/v1/me/onboarding', { headers });
    expect(repeated.status()).toBe(200);
    expect(await repeated.json()).toMatchObject({ user_id: initial.user_id, status: "active" });
    const refreshed = await mint(controls, identity);
    const workspaces = await request.get('/v1/workspaces', { headers: { authorization: `Bearer ${refreshed}` } });
    expect(workspaces.status()).toBe(200);
    expect((await workspaces.json()).items).toEqual([expect.objectContaining({ status: 'active' })]);
  } finally { await controls.put('/control/failures', { data: {} }); }
});
