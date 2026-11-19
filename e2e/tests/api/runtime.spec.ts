import { randomUUID } from 'node:crypto';
import { test, expect } from '../../fixtures/api.js';

test('native runtime, box containment, asynchronous HITL and owner-independent schedules', async ({
  account,
  identity,
  playwright,
}) => {
  test.setTimeout(180_000);
  const workspace = `/v1/workspaces/${account.workspaceId}`;
  const models = await account.api.get(`${workspace}/letas/models`);
  expect(models.ok(), await models.text()).toBeTruthy();
  const listed = (await models.json()).models;
  expect(listed).toEqual([{ model_id: 'openai/gpt-4.1-mini', reasoning_efforts: [null, 'low'] }]);
  const requestId = randomUUID();
  const creation = await account.api.post(`${workspace}/letas`, {
    data: {
      request_id: requestId,
      name: 'Workspace assistant',
      system_prompt: 'Perform workspace tasks and report the outcome.',
    },
  });
  expect(creation.ok(), await creation.text()).toBeTruthy();
  const root: { id: string } = await creation.json();
  const path = `${workspace}/letas/${root.id}`;
  await expect
    .poll(async () => (await (await account.api.get(path)).json()).state, {
      timeout: 30_000,
    })
    .toBe('active');
  const selection = `${path}/agents/${root.id}`;
  const selected = await account.api.patch(selection, {
    data: { model_id: 'openai/gpt-4.1-mini', reasoning_effort: 'low' },
  });
  expect(selected.ok(), await selected.text()).toBeTruthy();
  expect((await selected.json()).reasoning_effort).toBe('low');
  const changed = await account.api.patch(selection, { data: { model_id: 'openai/gpt-4.1-mini' } });
  expect(changed.ok(), await changed.text()).toBeTruthy();
  expect((await changed.json()).reasoning_effort).toBeNull();
  const reset = await account.api.patch(selection, { data: { model_id: null } });
  expect(reset.ok(), await reset.text()).toBeTruthy();
  expect((await reset.json()).model_id).toBeNull();
  expect((await account.api.patch(selection, { data: { reasoning_effort: 'low' } })).status()).toBe(
    422,
  );
  const input = {
    message_id: randomUUID(),
    content: 'Write a workspace report and run a shell calculation.',
  };
  const admitted = await account.api.post(`${path}/messages`, { data: input });
  expect(admitted.ok(), await admitted.text()).toBeTruthy();
  expect((await account.api.post(`${path}/messages`, { data: input })).ok()).toBeTruthy();
  await expect
    .poll(
      async () => {
        const result = await account.api.get(`${path}/agents/${root.id}/history`);
        expect(result.ok(), await result.text()).toBeTruthy();
        return (await result.json()).entries.some(
          (entry: { kind: string }) => entry.kind === 'final_note',
        );
      },
      { timeout: 45_000 },
    )
    .toBe(true);
  const rootView = await (await account.api.get(`${selection}/settings`)).json();
  const storage = `${workspace}/storages/${rootView.storage_id}`;
  const storageView = await (await account.api.get(storage)).json();
  const children = await account.api.get(`${storage}/nodes/${storageView.rootNodeId}/children`);
  expect(children.ok(), await children.text()).toBeTruthy();
  const rootReport: { id: string } = (await children.json()).nodes.find(
    (node: { name: string }) => node.name === 'report.txt',
  );
  expect(rootReport).toBeDefined();
  const report = await account.api.get(`${storage}/nodes/${rootReport.id}/text`);
  expect(report.ok(), await report.text()).toBeTruthy();
  expect((await report.json()).content).toBe('Native Leta runtime wrote this file.');
  const controller = new AbortController();
  const feed = await fetch(`http://envoy:8080${path}/events`, {
    headers: {
      Authorization: `Bearer ${await identity.sign('stream-test', account.id)}`,
    },
    signal: controller.signal,
  });
  expect(feed.status).toBe(200);
  const reader = feed.body!.getReader();
  const first = new TextDecoder().decode((await reader.read()).value);
  controller.abort();
  expect(first).toContain('openlet.snapshot');
  expect(first).toContain('next_cursor');
  const team = await account.api.post(`${path}/boxes`, {
    data: {
      request_id: randomUUID(),
      name: 'review',
      letis: [{ name: 'Reviewer', system_prompt: 'Review documents.' }],
      edges: [],
      representative: 'Reviewer',
    },
  });
  expect(team.ok(), await team.text()).toBeTruthy();
  const box = await team.json();
  const graph = await (await account.api.get(`${path}/boxes/${box.id}`)).json();
  const leti: string = graph.representative_agent_id;
  const questionId = randomUUID();
  const asked = await account.api.post(`${path}/hitl-requests`, {
    data: {
      type: 'ask',
      request_id: questionId,
      requester_agent_id: root.id,
      recipient_user_id: account.id,
      title: 'Review the report?',
      questions: [{ text: 'Which region?', options: ['North', 'South'] }],
    },
  });
  expect(asked.ok(), await asked.text()).toBeTruthy();
  const answered = await account.api.post(`/v1/hitl-requests/${questionId}/answer`, {
    data: {
      status: 'answered',
      response: { answers: { q1: { option_id: 'o1' } } },
    },
  });
  expect(answered.ok(), await answered.text()).toBeTruthy();
  const guest = await identity.createAccount();
  const invite = await account.api.post(`${workspace}/invitations`, {
    data: { email: guest.email, requestId: randomUUID() },
  });
  const accepted = await guest.api.post('/v1/invitations:accept', {
    data: { token: (await invite.json()).token },
  });
  expect(accepted.ok(), await accepted.text()).toBeTruthy();
  expect((await account.api.put(`${path}/operators/${guest.id}`)).ok()).toBeTruthy();
  const privateText = `Private note ${randomUUID()}`;
  const incoming = await guest.api.post(`${path}/messages`, {
    data: { message_id: randomUUID(), content: privateText },
  });
  expect(incoming.ok(), await incoming.text()).toBeTruthy();
  const privateMessages = await guest.api.get(`${path}/messages`);
  expect(await privateMessages.text()).toContain(privateText);
  expect(await (await account.api.get(`${path}/messages`)).text()).not.toContain(privateText);
  expect((await guest.api.get(`${path}/events`)).status()).toBe(403);
  const privateController = new AbortController();
  const privateFeed = await fetch(`http://envoy:8080${path}/messages/events`, {
    headers: { Authorization: `Bearer ${await identity.sign('private-stream', guest.id)}` },
    signal: privateController.signal,
  });
  expect(privateFeed.status).toBe(200);
  const privateSnapshot = new TextDecoder().decode(
    (await privateFeed.body!.getReader().read()).value,
  );
  privateController.abort();
  expect(privateSnapshot).toContain(privateText);
  expect(privateSnapshot).not.toContain('system_prompt');
  expect(privateSnapshot).not.toContain('"history"');
  const startsAt = new Date(Date.now() + 3_600_000).toISOString();
  const endsAt = new Date(Date.now() + 86_400_000).toISOString();
  const recurring = await account.api.post(`${path}/schedules`, {
    data: {
      request_id: randomUUID(),
      content: 'Review remaining work.',
      every_seconds: 600,
      starts_at: startsAt,
      ends_at: endsAt,
      timezone: 'Asia/Ho_Chi_Minh',
    },
  });
  expect(recurring.ok(), await recurring.text()).toBeTruthy();
  const original = await recurring.json();
  const changedSchedule = await account.api.patch(`${path}/schedules/${original.id}`, {
    data: { request_id: randomUUID(), every_seconds: 900, paused: true },
  });
  expect(changedSchedule.ok(), await changedSchedule.text()).toBeTruthy();
  expect((await changedSchedule.json()).spec).toEqual({ ...original.spec, every_seconds: 900 });
  const cleared = await account.api.patch(`${path}/schedules/${original.id}`, {
    data: { request_id: randomUUID(), ends_at: null },
  });
  expect(cleared.ok(), await cleared.text()).toBeTruthy();
  expect((await cleared.json()).spec.ends_at).toBeNull();
  const removed = await account.api.delete(`${path}/schedules/${original.id}`, {
    data: { request_id: randomUUID() },
  });
  expect(removed.ok(), await removed.text()).toBeTruthy();
  const transfer = await account.api.post(`${workspace}:transferOwnership`, {
    data: { newOwnerUserId: guest.id },
  });
  expect(transfer.ok(), await transfer.text()).toBeTruthy();
  await expect
    .poll(async () => {
      const list = await guest.api.get('/v1/workspaces');
      expect(list.ok(), await list.text()).toBeTruthy();
      return (await list.json()).workspaces.find(
        (item: { id: string }) => item.id === account.workspaceId,
      )?.role;
    })
    .toBe('WORKSPACE_ROLE_OWNER');
  const scheduledInstruction = `Read the workspace report and run a shell calculation. Audit ${root.id}`;
  const scheduled = await account.api.post(`${path}/schedules`, {
    data: {
      request_id: randomUUID(),
      target_box_id: box.id,
      after_seconds: 3,
      content: scheduledInstruction,
    },
  });
  expect(scheduled.ok(), await scheduled.text()).toBeTruthy();
  const leftAt = Date.now();
  const leave = await account.api.delete(`${workspace}/members/${account.id}`);
  expect(leave.ok(), await leave.text()).toBeTruthy();
  // An operator can chat, but cannot inspect or administer the owner's agent.
  expect((await guest.api.get(`${path}/agents/${leti}/history`)).status()).toBe(403);
  expect((await guest.api.get(`${path}/inbox`)).status()).toBe(403);
  expect(
    (
      await guest.api.post(`${path}/schedules`, {
        data: { request_id: randomUUID(), content: 'Unauthorized', after_seconds: 0 },
      })
    ).status(),
  ).toBe(403);
  // The new workspace owner cannot inspect private agent storage. Observe the
  // model's next request instead. Root and Leti share ~, so the fixture's
  // second create conflicts; its subsequent shell read must still succeed.
  const audit = await playwright.request.newContext({ baseURL: 'http://wiremock:8080' });
  let observed: unknown = [];
  try {
    await expect
      .poll(
        async () => {
          const response = await audit.post('/__admin/requests/find', {
            data: {
              method: 'POST',
              urlPath: '/v1/chat/completions',
              bodyPatterns: [{ contains: scheduledInstruction }],
            },
          });
          expect(response.ok(), await response.text()).toBeTruthy();
          const records = await response.json();
          observed = records.requests.map((entry: { loggedDate: number; body: string }) => ({
            loggedDate: entry.loggedDate,
            leftAt,
            messages: JSON.parse(entry.body).messages,
          }));
          return records.requests.some((entry: { loggedDate: number; body: string }) => {
            if (entry.loggedDate < leftAt) return false;
            const request = JSON.parse(entry.body);
            return request.messages.some(
              (message: { role: string; tool_call_id?: string; content: string }) => {
                return (
                  message.role === 'tool' &&
                  message.tool_call_id === 'reuse-session' &&
                  message.content === 'Native Leta runtime wrote this file.'
                );
              },
            );
          });
        },
        { timeout: 60000 },
      )
      .toBe(true);
  } catch (error) {
    await test.info().attach('scheduled-model-requests', {
      body: JSON.stringify(observed, null, 2),
      contentType: 'application/json',
    });
    throw error;
  } finally {
    await audit.dispose();
  }
  const deleted = await guest.api.delete(workspace);
  expect(deleted.ok(), await deleted.text()).toBeTruthy();
  await expect
    .poll(async () => (await guest.api.get(workspace)).status(), {
      timeout: 30_000,
    })
    .toBe(403);
});
