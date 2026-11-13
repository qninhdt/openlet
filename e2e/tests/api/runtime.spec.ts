import { randomUUID } from 'node:crypto';
import { test, expect } from '../../fixtures/api.js';

test('native runtime, box containment, asynchronous HITL and owner-independent schedules', async ({
  account,
  identity,
}) => {
  test.setTimeout(180_000);
  const workspace = `/v1/workspaces/${account.workspaceId}`;
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
  const rootView = await (await account.api.get(path)).json();
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
      name: 'Review',
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
  const leave = await account.api.delete(`${workspace}/members/${account.id}`);
  expect(leave.ok(), await leave.text()).toBeTruthy();
  const scheduled = await guest.api.post(`${path}/schedules`, {
    data: {
      request_id: randomUUID(),
      target_box_id: box.id,
      after_seconds: 0,
      content: 'Write a report in your own team home.',
    },
  });
  expect(scheduled.ok(), await scheduled.text()).toBeTruthy();
  await expect
    .poll(
      async () => {
        const response = await guest.api.get(`${path}/agents/${leti}/history`);
        expect(response.ok(), await response.text()).toBeTruthy();
        return (await response.json()).entries.some(
          (entry: { kind: string }) => entry.kind === 'final_note',
        );
      },
      { timeout: 45_000 },
    )
    .toBe(true);
  // Agent storage access survives its human owner's removal from the workspace.
  const state = await (await guest.api.get(`${path}/agents/${leti}/history`)).json();
  const results: { id: string; kind: string }[] = state.entries.filter(
    (entry: { kind: string }) => entry.kind === 'tool_result',
  );
  expect(results.length).toBeGreaterThanOrEqual(2);
  const contents: string[] = [];
  for (const entry of results) {
    const detail = await guest.api.get(`${path}/agents/${leti}/history/${entry.id}`);
    expect(detail.ok(), await detail.text()).toBeTruthy();
    contents.push((await detail.json()).content);
  }
  expect(rootReport.id).toBeTruthy();
  expect(contents.join('\n')).toContain('native-shell');
  expect(contents.join('\n')).toContain('Native Leta runtime wrote this file.');
  expect(contents.join('\n')).not.toMatch(/permission denied|not configured|Traceback/i);
  expect(
    (
      await guest.api.delete(`${path}/boxes/${box.id}`, {
        data: { request_id: randomUUID() },
      })
    ).ok(),
  ).toBeTruthy();
  const deleted = await guest.api.delete(workspace);
  expect(deleted.ok(), await deleted.text()).toBeTruthy();
  await expect
    .poll(async () => (await guest.api.get(workspace)).status(), {
      timeout: 30_000,
    })
    .toBe(404);
});
