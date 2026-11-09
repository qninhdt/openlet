import { randomUUID } from 'node:crypto';
import type { APIRequestContext } from '@playwright/test';
import { test, expect, inline, mint, onboard } from '../../fixtures/api-test.ts';
import { recordWorkflowHistory } from '../../fixtures/temporal-control.ts';
import { setLetaWorkerRunning } from '../../fixtures/restart-service.ts';
import { gateway } from '../../setup/settings.ts';

function call(name: string, args: Record<string, unknown>) {
  return { content: '', tool_calls: [{ id: randomUUID(), type: 'function', function: { name, arguments: JSON.stringify(args) } }] };
}
const note = (content: string) => ({ content });
const key = () => ({ 'idempotency-key': randomUUID() });

async function watch(path: string, token: string, after?: string) {
  const controller = new AbortController();
  const response = await fetch(`${gateway}${path}`, { signal: controller.signal, headers: {
    authorization: `Bearer ${token}`, ...(after ? { 'last-event-id': after } : {}),
  } });
  expect(response.status).toBe(200);
  expect(response.headers.get('content-type')).toContain('text/event-stream');
  const frames: Array<{ id?: string; data: any }> = [];
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  const pumping = (async () => {
    let buffer = '';
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) return;
        buffer += decoder.decode(value, { stream: true });
        let boundary: number;
        while ((boundary = buffer.indexOf('\n\n')) !== -1) {
          const lines = buffer.slice(0, boundary).split('\n');
          buffer = buffer.slice(boundary + 2);
          const data = lines.find(line => line.startsWith('data: '));
          if (data) frames.push({ id: lines.find(line => line.startsWith('id: '))?.slice(4), data: JSON.parse(data.slice(6)) });
        }
      }
    } catch (error) { if (!controller.signal.aborted) throw error; }
    finally { reader.releaseLock(); }
  })();
  return { frames, close: async () => { controller.abort(); await pumping; } };
}

async function json(api: APIRequestContext, path: string) {
  const response = await api.get(path);
  expect(response.status(), await response.text()).toBe(200);
  return response.json();
}

async function create(api: APIRequestContext, workspaceId: string, marker: string) {
  const response = await api.post('/v1/letas', { headers: key(), data: {
    workspace_id: workspaceId, name: 'Research Leta', description: 'Acceptance',
    system_prompt: marker, model_id: 'e2e-agent', reasoning_effort: null,
  } });
  expect(response.status(), await response.text()).toBe(201);
  return response.json();
}

test('independent agents ask humans, process a reminder and return a box result through real services', async ({ session, controls, identity, playwright }) => {
  const guestIdentity = await (await controls.post('/control/users', { data: { email: `${randomUUID()}@example.test` } })).json();
  const resourceOwner = await onboard(controls, guestIdentity, playwright.request);
  let stream: Awaited<ReturnType<typeof watch>> | undefined;
  try {
    const ws = `/v1/workspaces/${session.workspaceId}`;
    const joined = await session.api.post(`${ws}/members`, { data: { user_id: resourceOwner.userId, role: 'member' } });
    expect(joined.status(), await joined.text()).toBe(201);
    const personalScope = (await json(session.api, `${ws}/members`)).items.find((member: any) => member.user.id === resourceOwner.userId).personal_scope_id;
    const personalBase = `/v1/filesystems/${session.filesystemId}/scopes/${personalScope}`;
    const personalRoot = (await json(resourceOwner.api, `${personalBase}/nodes:resolve?path=/`)).id;
    await inline({ ...session, api: resourceOwner.api, scopeId: personalScope, rootId: personalRoot }, 'research.txt', Buffer.from('Resource owner evidence\n'), personalRoot, 'text/plain');
    const marker = `acceptance-${randomUUID()}`;
    const prompts = { root: `${marker}-root`, rep: `${marker}-representative`, peer: `${marker}-researcher` };
    const questions = [
      { type: 'single_choice', id: 'one', text: 'Choose one', options: [{ id: 'a', label: 'A' }] },
      { type: 'multiple_choice', id: 'many', text: 'Choose several', options: [{ id: 'a', label: 'A' }] },
      { type: 'text', id: 'text', text: 'Describe the report' },
    ];
    const scripts = {
      [prompts.root]: [
        call('create_box', { name: 'Reports', description: 'Research team', representative: 'Representative',
          letis: [{ name: 'Representative', description: 'Delegates', system_prompt: prompts.rep },
            { name: 'Researcher', description: 'Researches', system_prompt: prompts.peer }], edges: [['Representative', 'Researcher']] }),
        call('send_message', { to: 'Reports', content: 'Prepare the report' }), note('Waiting for the team'),
        call('send_message', { to: 'owner', content: 'Independent reminder delivered' }), note('Reminder sent'),
        call('send_message', { to: 'owner', content: 'Report completed using the approved evidence' }), note('Result sent'),
      ],
      [prompts.rep]: [call('send_message', { to: 'Researcher', content: 'Research this report' }), note('Waiting for research'),
        call('send_message', { to: 'parent', content: 'The report is ready' }), note('Result returned to the parent box')],
      [prompts.peer]: [call('ask_user', { title: 'Report questions', questions }), note('Questions sent; waiting'),
        call('request_access', { resource: { type: 'personal_scope', user_id: resourceOwner.userId }, reason: 'Read evidence' }), note('Waiting for resource owner'),
        call('read_file', { path: `/users/${resourceOwner.userId}/research.txt` }),
        call('send_message', { to: 'Representative', content: 'Research completed from the approved file' }), note('Research result sent')],
    };
    for (const [marker, responses] of Object.entries(scripts)) {
      expect((await controls.put('/control/agent-model', { data: { marker, responses } })).status()).toBe(200);
    }
    const root = await create(session.api, session.workspaceId, prompts.root);
    const base = `/v1/letas/${root.id}`;
    const token = await mint(controls, identity);
    stream = await watch(`${base}/events`, token);
    const sentId = randomUUID();
    const input = { id: sentId, content: 'Prepare a report and ask any questions you need' };
    for (let retry = 0; retry < 2; retry++) {
      const sent = await session.api.post(`${base}/messages`, { data: input });
      expect(sent.status(), await sent.text()).toBe(201);
      expect(await sent.json()).toMatchObject({ id: sentId, recipient_agent_id: root.id, seq: 1 });
    }
    let ask: any;
    await expect.poll(async () => {
      ask = (await json(session.api, '/v1/human-requests?status=pending')).items.find((r: any) => r.leta_id === root.id && r.kind === 'ask');
      return ask?.title;
    }).toBe('Report questions');
    const box = (await json(session.api, `${base}/boxes`)).items[0];
    const graph = await json(session.api, `${base}/boxes/${box.id}`);
    const researcher = graph.letis.find((agent: any) => agent.name === 'Researcher');
    expect(graph.edges).toHaveLength(1);
    expect(ask).toMatchObject({ requester_agent_id: researcher.id, approver_user_id: session.userId });
    await expect.poll(() => stream!.frames.filter(frame => frame.data.agent_id === researcher.id).length).toBeGreaterThan(0);
    expect(stream.frames.every(frame => frame.data.leta_id === root.id)).toBe(true);
    const reconnectAfter = stream.frames.findLast(frame => frame.id)?.id;
    expect(reconnectAfter).toBeTruthy();
    await stream.close();
    await expect.poll(async () => (await json(session.api, `${base}/history?limit=100`)).items.filter((entry: any) => entry.kind === 'final_note').length).toBe(1);
    const schedule = await session.api.post(`${base}/schedules`, { headers: key(), data: {
      title: 'Independent reminder', content: 'Remind owner now', spec: { type: 'at', after_seconds: 2 },
    } });
    expect(schedule.status(), await schedule.text()).toBe(201);
    await expect.poll(async () => (await json(session.api, `${base}/messages`)).items.map((m: any) => m.content)).toContain('Independent reminder delivered');
    expect((await json(session.api, `/v1/human-requests/${ask.id}`)).status).toBe('pending');
    const answer = await session.api.post(`/v1/human-requests/${ask.id}/response`, { data: { action: 'answer', answers: {
      one: { option_id: null, note: 'No preference' }, many: { option_ids: [], note: 'Use judgment' }, text: { text: 'Read the private evidence' },
    } } });
    expect(answer.status(), await answer.text()).toBe(200);
    let approval: any;
    await expect.poll(async () => {
      approval = (await json(resourceOwner.api, '/v1/human-requests?status=pending')).items.find((r: any) => r.leta_id === root.id);
      return approval?.kind;
    }).toBe('approval');
    expect(approval.approver_user_id).toBe(resourceOwner.userId);
    expect((await session.api.post(`/v1/human-requests/${approval.id}/response`, { data: { action: 'accept' } })).status()).toBe(404);
    const accepted = await resourceOwner.api.post(`/v1/human-requests/${approval.id}/response`, { data: { action: 'accept' } });
    expect(accepted.status(), await accepted.text()).toBe(200);
    await expect.poll(async () => (await json(session.api, `${base}/messages`)).items.map((m: any) => m.content)).toContain('Report completed using the approved evidence');
    const history = await json(session.api, `${base}/history?agent_id=${researcher.id}&limit=100`);
    expect(history.items.filter((e: any) => e.kind === 'inbox_input').every((e: any) => e.data.mode === 'full')).toBe(true);
    const read = history.items.find((e: any) => e.kind === 'tool_result' && e.data.name === 'read_file');
    expect(read.data.outcome).toBe('success');
    expect(JSON.stringify(read.data)).toContain('Resource owner evidence');
    stream = await watch(`${base}/events`, token, reconnectAfter);
    await expect.poll(() => stream!.frames.some(frame => frame.data.agent_id === researcher.id
      && frame.data.event.type === 'TOOL_CALL_START' && frame.data.event.toolCallName === 'read_file')).toBe(true);
    expect(stream.frames.some(frame => frame.data.event.name === 'resync_required')).toBe(false);
    const [afterTime, afterSequence] = reconnectAfter!.split('-').map(BigInt);
    expect(stream.frames.filter(frame => frame.id).every(frame => {
      const [time, sequence] = frame.id!.split('-').map(BigInt);
      return time > afterTime || time === afterTime && sequence > afterSequence;
    })).toBe(true);
    await stream.close();
    expect((await session.api.get(`${personalBase}/nodes:resolve?path=/`)).status()).toBe(403);
    const scopes = await json(session.api, `${ws}/scopes?leta_id=${root.id}`);
    expect(scopes.items.find((item: any) => item.id === personalScope)).toMatchObject({ read_content: true, write: false });
    const revoke = await resourceOwner.api.delete(`${ws}/scopes/${personalScope}/access/${root.id}`, { data: { grantee_kind: 'leta', role: 'viewer' } });
    expect(revoke.status(), await revoke.text()).toBe(204);
    expect((await json(session.api, `${ws}/scopes?leta_id=${root.id}`)).items.some((item: any) => item.id === personalScope)).toBe(false);
    const archived = await session.api.delete(base, { headers: key() });
    expect(archived.status(), await archived.text()).toBe(200);
    expect(await archived.json()).toMatchObject({ status: 'archived' });
    expect((await json(session.api, `${base}/messages`)).items.filter((m: any) => m.recipient_user_id)).toHaveLength(2);
    await recordWorkflowHistory('LetaLifecycleWorkflow', `leta-lifecycle/${root.id}`);
    expect((await session.api.delete(ws)).status()).toBe(204);
  } finally { await stream?.close(); await resourceOwner.api.dispose(); }
});

test('creator departure removes resource and home visibility while workspace deletion still cleans the resource', async ({ session, controls, playwright }) => {
  const identity = await (await controls.post('/control/users', { data: { email: `${randomUUID()}@example.test` } })).json();
  const creator = await onboard(controls, identity, playwright.request);
  try {
    const ws = `/v1/workspaces/${session.workspaceId}`;
    const joined = await session.api.post(`${ws}/members`, { data: { user_id: creator.userId, role: 'member' } });
    expect(joined.status(), await joined.text()).toBe(201);
    const root = await create(creator.api, session.workspaceId, `idle-${randomUUID()}`);
    const base = `/v1/letas/${root.id}`;
    expect((await creator.api.get(base)).status()).toBe(200);
    const homeScope = (await json(creator.api, `${ws}/scopes?leta_id=${root.id}`)).items.find((scope: any) => scope.kind === 'home');
    expect(homeScope).toBeTruthy();
    const home = `/v1/filesystems/${session.filesystemId}/scopes/${homeScope.id}/nodes:resolve?path=/`;
    expect((await creator.api.get(home)).status()).toBe(200);
    const departed = await creator.api.delete(`${ws}/members/${creator.userId}`);
    expect(departed.status(), await departed.text()).toBe(204);
    expect((await creator.api.get(base)).status()).toBe(403);
    expect((await creator.api.get(home)).status()).toBe(403);
    expect((await json(creator.api, `/v1/letas?workspace_id=${session.workspaceId}`)).items).toEqual([]);
    const deleted = await session.api.delete(ws);
    expect(deleted.status(), await deleted.text()).toBe(204);
  } finally { await creator.api.dispose(); }
});

test('deleting a box settles its pending question and schedules while retaining committed inbox input', async ({ session, controls }) => {
  const marker = `delete-box-${randomUUID()}`;
  for (const [role, responses] of Object.entries({
    root: [call('send_message', { to: 'Pending box', content: 'Ask before researching' }), note('Waiting for the box')],
    child: [call('ask_user', { title: 'Question to cancel', questions: [{ type: 'text', id: 'answer', text: 'Continue?' }] }), note('Waiting for the answer')],
  })) {
    expect((await controls.put('/control/agent-model', { data: { marker: `${marker}-${role}`, responses } })).status()).toBe(200);
  }
  const root = await create(session.api, session.workspaceId, `${marker}-root`);
  const base = `/v1/letas/${root.id}`;
  const created = await session.api.post(`${base}/boxes`, { headers: key(), data: {
    name: 'Pending box', letis: [{ name: 'Pending researcher', system_prompt: `${marker}-child` }], edges: [], representative: 'Pending researcher',
  } });
  expect(created.status(), await created.text()).toBe(201);
  const box = await created.json();
  expect((await session.api.post(`${base}/messages`, { data: { id: randomUUID(), content: 'Start the box' } })).status()).toBe(201);
  let ask: any;
  await expect.poll(async () => {
    ask = (await json(session.api, '/v1/human-requests?status=pending')).items.find((item: any) => item.leta_id === root.id);
    return ask?.title;
  }).toBe('Question to cancel');
  expect((await session.api.post(`${base}/pause`, { headers: key() })).status()).toBe(200);
  const schedules = [];
  for (const after_seconds of [1, 3600]) {
    const response = await session.api.post(`${base}/schedules`, { headers: key(), data: {
      title: `Box wake ${after_seconds}`, content: 'Queued box input', box_id: box.id, spec: { type: 'at', after_seconds },
    } });
    expect(response.status(), await response.text()).toBe(201);
    schedules.push(await response.json());
  }
  const inbox = `${base}/inbox?agent_id=${box.representative_agent_id}`;
  await expect.poll(async () => (await json(session.api, inbox)).items.some((item: any) => item.source_type === 'schedule')).toBe(true);
  const before = (await json(session.api, inbox)).items.map((item: any) => item.id);
  const deleted = await session.api.delete(`${base}/boxes/${box.id}`, { headers: key() });
  expect(deleted.status(), await deleted.text()).toBe(200);
  expect(await deleted.json()).toMatchObject({ id: box.id, status: 'archived' });
  expect((await json(session.api, `/v1/human-requests/${ask.id}`)).status).toBe('cancelled');
  expect((await session.api.post(`/v1/human-requests/${ask.id}/response`, { data: { action: 'answer', answers: { answer: { text: 'Too late' } } } })).status()).toBe(409);
  for (const schedule of schedules) expect((await json(session.api, `${base}/schedules/${schedule.id}`)).forecast_status).toBe('deleted');
  expect((await json(session.api, inbox)).items.map((item: any) => item.id)).toEqual(before);
  expect((await json(session.api, `${base}/boxes/${box.id}`)).letis.every((agent: any) => agent.status === 'archived')).toBe(true);
  expect((await session.api.delete(`/v1/workspaces/${session.workspaceId}`)).status()).toBe(204);
});

test('revoking a warm personal mount during a child model call blocks cached reads and direct owner messaging', async ({ session, controls, playwright }) => {
  const identity = await (await controls.post('/control/users', { data: { email: `${randomUUID()}@example.test` } })).json();
  const resourceOwner = await onboard(controls, identity, playwright.request);
  const marker = `warm-revoke-${randomUUID()}`;
  const gate = `/control/agent-model?marker=${marker}-child`;
  try {
    const ws = `/v1/workspaces/${session.workspaceId}`;
    expect((await session.api.post(`${ws}/members`, { data: { user_id: resourceOwner.userId, role: 'member' } })).status()).toBe(201);
    const scope = (await json(session.api, `${ws}/members`)).items.find((item: any) => item.user.id === resourceOwner.userId).personal_scope_id;
    const personal = `/v1/filesystems/${session.filesystemId}/scopes/${scope}`;
    const personalRoot = (await json(resourceOwner.api, `${personal}/nodes:resolve?path=/`)).id;
    const secret = `private-${randomUUID()}`;
    const file = await inline({ ...session, api: resourceOwner.api, scopeId: scope, rootId: personalRoot }, 'private.txt', Buffer.from(secret), personalRoot, 'text/plain');
    const path = `/users/${resourceOwner.userId}/private.txt`;
    expect((await controls.put('/control/agent-model', { data: { marker: `${marker}-root`, responses: [
      call('send_message', { to: 'Private research', content: 'Read approved evidence' }), note('Waiting for research'),
      call('send_message', { to: 'owner', content: 'Research finished after access was revoked' }), note('Result sent'),
    ] } })).status()).toBe(200);
    expect((await controls.put('/control/agent-model', { data: { marker: `${marker}-child`, pause_at: 6, responses: [
      call('request_access', { resource: { type: 'personal_scope', user_id: resourceOwner.userId }, role: 'viewer', reason: 'Read private evidence' }),
      note('Waiting for resource owner'), call('read_file', { path }), call('read_file', { path }),
      call('write_file', { path, content: 'Must not overwrite a viewer file' }), call('read_file', { path }),
      call('send_message', { to: 'owner', content: 'Forbidden direct child message' }),
      call('send_message', { to: 'parent', content: 'Access revoked; no further private read' }), note('Returned safely'),
    ] } })).status()).toBe(200);
    const root = await create(session.api, session.workspaceId, `${marker}-root`);
    const base = `/v1/letas/${root.id}`;
    const created = await session.api.post(`${base}/boxes`, { headers: key(), data: {
      name: 'Private research', letis: [{ name: 'Private reader', system_prompt: `${marker}-child` }], edges: [], representative: 'Private reader',
    } });
    expect(created.status(), await created.text()).toBe(201);
    const box = await created.json();
    expect((await session.api.post(`${base}/messages`, { data: { id: randomUUID(), content: 'Start private research' } })).status()).toBe(201);
    let approval: any;
    await expect.poll(async () => {
      approval = (await json(resourceOwner.api, '/v1/human-requests?status=pending')).items.find((item: any) => item.leta_id === root.id);
      return approval?.kind;
    }).toBe('approval');
    expect((await resourceOwner.api.post(`/v1/human-requests/${approval.id}/response`, { data: { action: 'accept' } })).status()).toBe(200);
    await expect.poll(async () => (await json(controls, gate)).blocked).toBe(true);
    const childHistory = `${base}/history?agent_id=${box.representative_agent_id}&limit=100`;
    const before = (await json(session.api, childHistory)).items.filter((entry: any) => entry.kind === 'tool_result');
    expect(before.filter((entry: any) => entry.data.name === 'read_file' && entry.data.outcome === 'success')).toHaveLength(2);
    expect(before.find((entry: any) => entry.data.name === 'write_file').data.outcome).toBe('error');
    expect((await resourceOwner.api.delete(`${ws}/scopes/${scope}/access/${root.id}`, { data: { grantee_kind: 'leta', role: 'viewer' } })).status()).toBe(204);
    expect((await controls.post(gate)).status()).toBe(200);
    await expect.poll(async () => (await json(session.api, `${base}/messages`)).items.map((item: any) => item.content)).toContain('Research finished after access was revoked');
    const results = (await json(session.api, childHistory)).items.filter((entry: any) => entry.kind === 'tool_result');
    const reads = results.filter((entry: any) => entry.data.name === 'read_file');
    expect(reads).toHaveLength(3);
    expect(reads[2].data.outcome).toBe('error');
    expect(JSON.stringify(reads[2].data)).not.toContain(secret);
    expect(results.find((entry: any) => entry.data.name === 'send_message').data.outcome).toBe('error');
    expect((await json(session.api, `${base}/messages`)).items.some((item: any) => item.content === 'Forbidden direct child message')).toBe(false);
    expect(await (await resourceOwner.api.get(`${personal}/nodes/${file.id}/content`)).body()).toEqual(Buffer.from(secret));
    expect((await json(session.api, `${ws}/scopes?leta_id=${root.id}`)).items.some((item: any) => item.id === scope)).toBe(false);
    expect((await session.api.delete(ws)).status()).toBe(204);
  } finally { await controls.post(gate); await resourceOwner.api.dispose(); }
});

test('a cancelled child form is replaced while Leta handles other work and duplicate answers resume only once', async ({ session, controls }) => {
  const marker = `replace-form-${randomUUID()}`;
  expect((await controls.put('/control/agent-model', { data: { marker: `${marker}-root`, responses: [
    call('send_message', { to: 'Question box', content: 'Ask for the report format' }), note('Waiting for the box'),
    call('send_message', { to: 'owner', content: 'Other work completed while the replacement form is pending' }), note('Other work sent'),
    call('send_message', { to: 'owner', content: 'Completed using the replacement answer' }), note('Report sent'),
  ] } })).status()).toBe(200);
  expect((await controls.put('/control/agent-model', { data: { marker: `${marker}-child`, responses: [
    call('ask_user', { title: 'Original question', questions: [{ type: 'text', id: 'old', text: 'Old report format?' }] }), note('Waiting for original answer'),
  ] } })).status()).toBe(200);
  const root = await create(session.api, session.workspaceId, `${marker}-root`);
  const base = `/v1/letas/${root.id}`;
  const created = await session.api.post(`${base}/boxes`, { headers: key(), data: {
    name: 'Question box', letis: [{ name: 'Questioner', system_prompt: `${marker}-child` }], edges: [], representative: 'Questioner',
  } });
  expect(created.status(), await created.text()).toBe(201);
  const box = await created.json();
  expect((await session.api.post(`${base}/messages`, { data: { id: randomUUID(), content: 'Prepare a report' } })).status()).toBe(201);
  let original: any;
  await expect.poll(async () => {
    original = (await json(session.api, '/v1/human-requests?status=pending')).items.find((item: any) => item.leta_id === root.id);
    const history = await json(session.api, `${base}/history?agent_id=${box.representative_agent_id}`);
    return Boolean(original && history.items.some((entry: any) => entry.kind === 'final_note'));
  }).toBe(true);
  expect((await controls.put('/control/agent-model', { data: { marker: `${marker}-child`, responses: [
    call('ask_user', { title: 'Replacement questions', questions: [
      { type: 'single_choice', id: 'format', text: 'Format?', options: [{ id: 'brief', label: 'Brief' }] },
      { type: 'multiple_choice', id: 'topics', text: 'Topics?', options: [{ id: 'price', label: 'Price' }] },
      { type: 'text', id: 'note', text: 'Anything else?' },
    ] }), note('Waiting for replacement answer'),
    call('send_message', { to: 'parent', content: 'Completed with replacement answer' }), note('Replacement applied'),
  ] } })).status()).toBe(200);
  const cancelled = await session.api.post(`${base}/human-requests/${original.id}/cancel`, { data: { reason: 'The original question is obsolete' } });
  expect(cancelled.status(), await cancelled.text()).toBe(200);
  expect((await cancelled.json()).status).toBe('cancelled');
  expect((await session.api.post(`/v1/human-requests/${original.id}/response`, { data: { action: 'answer', answers: { old: { text: 'Too late' } } } })).status()).toBe(409);
  let replacement: any;
  await expect.poll(async () => {
    replacement = (await json(session.api, '/v1/human-requests?status=pending')).items.find((item: any) => item.leta_id === root.id && item.id !== original.id);
    return replacement?.title;
  }).toBe('Replacement questions');
  expect(replacement.requester_agent_id).toBe(box.representative_agent_id);
  expect((await session.api.post(`${base}/messages`, { data: { id: randomUUID(), content: 'Handle this unrelated request now' } })).status()).toBe(201);
  await expect.poll(async () => (await json(session.api, `${base}/messages`)).items.map((item: any) => item.content)).toContain('Other work completed while the replacement form is pending');
  expect((await json(session.api, `/v1/human-requests/${replacement.id}`)).status).toBe('pending');
  const answers = { format: { option_id: null, note: 'Use your judgment' }, topics: { option_ids: [], note: 'No preference' }, note: { text: '' } };
  const invalid = await session.api.post(`/v1/human-requests/${replacement.id}/response`, { data: { action: 'answer', answers: { ...answers, format: { option_id: 'unknown' } } } });
  expect(invalid.status(), await invalid.text()).toBe(400);
  expect((await json(session.api, `/v1/human-requests/${replacement.id}`)).status).toBe('pending');
  const responses = await Promise.all(Array.from({ length: 2 }, () => session.api.post(`/v1/human-requests/${replacement.id}/response`, { data: { action: 'answer', answers } })));
  for (const response of responses) expect(response.status(), await response.text()).toBe(200);
  const changed = await session.api.post(`/v1/human-requests/${replacement.id}/response`, { data: { action: 'answer', answers: { ...answers, note: { text: 'Changed after completion' } } } });
  expect(changed.status(), await changed.text()).toBe(409);
  await expect.poll(async () => (await json(session.api, `${base}/messages`)).items.filter((item: any) => item.content === 'Completed using the replacement answer').length).toBe(1);
  const inbox = (await json(session.api, `${base}/inbox?agent_id=${box.representative_agent_id}`)).items;
  expect(inbox.filter((item: any) => item.source_type === 'hitl' && item.source_id === replacement.id)).toHaveLength(1);
  expect(inbox.filter((item: any) => item.source_type === 'hitl' && item.source_id === original.id)).toHaveLength(1);
  expect((await session.api.delete(`/v1/workspaces/${session.workspaceId}`)).status()).toBe(204);
});

test('an overdue reminder and unacknowledged owner input survive a worker outage and paused resume without duplicates', async ({ session, controls }) => {
  const marker = `worker-outage-${randomUUID()}`;
  expect((await controls.put('/control/agent-model', { data: { marker, responses: [
    call('send_message', { to: 'owner', content: 'Processed the queued input and overdue reminder' }), note('Recovered work completed'),
  ] } })).status()).toBe(200);
  const root = await create(session.api, session.workspaceId, marker);
  const base = `/v1/letas/${root.id}`;
  expect((await session.api.post(`${base}/pause`, { headers: key() })).status()).toBe(200);
  const at = new Date(Math.ceil(Date.now() / 1000) * 1000 + 5000).toISOString();
  const scheduled = await session.api.post(`${base}/schedules`, { headers: key(), data: {
    title: 'Due while worker is down', content: 'Overdue reminder', spec: { type: 'at', at },
  } });
  expect(scheduled.status(), await scheduled.text()).toBe(201);
  const schedule = await scheduled.json();
  const input = { id: randomUUID(), content: 'Owner input during worker outage' };
  try {
    await setLetaWorkerRunning(false);
    const pending = await session.api.post(`${base}/messages`, { data: input, timeout: 30_000 });
    expect(pending.status(), await pending.text()).toBe(202);
    expect(await pending.json()).toMatchObject({ status: 'pending', resource_id: input.id });
    expect((await json(session.api, `${base}/inbox`)).items.some((item: any) => item.id === input.id)).toBe(false);
  } finally { await setLetaWorkerRunning(true); }
  await expect.poll(async () => (await session.api.post(`${base}/messages`, { data: input })).status()).toBe(201);
  await expect.poll(async () => (await json(session.api, `${base}/inbox`)).items.length).toBe(2);
  const inbox = (await json(session.api, `${base}/inbox`)).items;
  expect(inbox.filter((item: any) => item.id === input.id)).toHaveLength(1);
  const reminders = inbox.filter((item: any) => item.source_type === 'schedule' && item.source_id === schedule.id);
  expect(reminders).toHaveLength(1);
  expect(new Date(reminders[0].data.scheduled_at).getTime()).toBe(new Date(at).getTime());
  expect((await json(session.api, `${base}/history`)).items).toEqual([]);
  expect((await session.api.post(`${base}/resume`, { headers: key() })).status()).toBe(200);
  await expect.poll(async () => (await json(session.api, `${base}/messages`)).items.filter((item: any) => item.content === 'Processed the queued input and overdue reminder').length).toBe(1);
  await expect.poll(async () => (await json(session.api, `${base}/history`)).items.filter((entry: any) => entry.kind === 'final_note').length).toBe(1);
  expect((await json(session.api, `${base}/inbox`)).items).toHaveLength(2);
  expect((await session.api.delete(`/v1/workspaces/${session.workspaceId}`)).status()).toBe(204);
});

test('owner input, a reminder and a box result join the next model boundary exactly once', async ({ session, controls }) => {
  const marker = `steering-${randomUUID()}`;
  const gate = `/control/agent-model?marker=${marker}-root`;
  expect((await controls.put('/control/agent-model', { data: { marker: `${marker}-root`, pause_at: 1, responses: [
    call('get_workspace', {}), call('send_message', { to: 'owner', content: 'Handled all three arrivals' }), note('Collected the arrivals'),
  ] } })).status()).toBe(200);
  expect((await controls.put('/control/agent-model', { data: { marker: `${marker}-child`, responses: [
    call('send_message', { to: 'parent', content: 'Box result during the root model call' }), note('Box result sent'),
  ] } })).status()).toBe(200);
  const root = await create(session.api, session.workspaceId, `${marker}-root`);
  const base = `/v1/letas/${root.id}`;
  const created = await session.api.post(`${base}/boxes`, { headers: key(), data: {
    name: 'Steering box', letis: [{ name: 'Steering representative', system_prompt: `${marker}-child` }], edges: [], representative: 'Steering representative',
  } });
  expect(created.status(), await created.text()).toBe(201);
  const box = await created.json();
  try {
    const first = { id: randomUUID(), content: 'Start work before the arrivals' };
    expect((await session.api.post(`${base}/messages`, { data: first })).status()).toBe(201);
    await expect.poll(async () => (await json(controls, gate)).blocked).toBe(true);
    const next = { id: randomUUID(), content: 'New owner instructions while model is busy' };
    for (let retry = 0; retry < 2; retry++) {
      expect((await session.api.post(`${base}/messages`, { data: next })).status()).toBe(201);
    }
    for (const target of [{}, { box_id: box.id }]) {
      const scheduled = await session.api.post(`${base}/schedules`, { headers: key(), data: {
        title: 'Concurrent wake', content: 'Scheduled steering content', ...target, spec: { type: 'at', after_seconds: 1 },
      } });
      expect(scheduled.status(), await scheduled.text()).toBe(201);
    }
    await expect.poll(async () => (await json(session.api, `${base}/inbox?limit=100`)).items.length).toBe(4);
    expect((await json(controls, gate)).blocked).toBe(true);
    expect((await controls.post(gate)).status()).toBe(200);
    await expect.poll(async () => (await json(session.api, `${base}/history?limit=100`)).items.filter((entry: any) => entry.kind === 'final_note').length).toBe(1);
    const history = (await json(session.api, `${base}/history?limit=100`)).items;
    const batches = history.filter((entry: any) => entry.kind === 'inbox_input');
    expect(batches.map((entry: any) => [entry.data.mode, entry.data.cursor_from, entry.data.cursor_to])).toEqual([
      ['digest', 0, 1], ['digest', 1, 4],
    ]);
    const inbox = (await json(session.api, `${base}/inbox?limit=100`)).items;
    const collected = batches.flatMap((entry: any) => entry.data.groups.flatMap((group: any) => group.message_ids));
    expect([...collected].sort()).toEqual(inbox.map((item: any) => item.id).sort());
    expect(batches[1].data.groups.map((group: any) => group.source.type).sort()).toEqual(['box', 'owner', 'schedule']);
    const toolResult = history.find((entry: any) => entry.kind === 'tool_result' && entry.data.name === 'get_workspace');
    const sendCall = history.find((entry: any) => entry.kind === 'tool_call' && entry.data.name === 'send_message');
    expect(toolResult.seq).toBeLessThan(batches[1].seq);
    expect(batches[1].seq).toBeLessThan(sendCall.seq);
    expect(new Set(history.map((entry: any) => entry.run_id)).size).toBe(1);
    const child = (await json(session.api, `${base}/history?agent_id=${box.representative_agent_id}&limit=100`)).items;
    const childInput = child.find((entry: any) => entry.kind === 'inbox_input');
    expect(childInput.data).toMatchObject({ mode: 'full', items: [{ content: 'Scheduled steering content' }] });
    expect((await json(session.api, `${base}/messages`)).items.filter((item: any) => item.content === 'Handled all three arrivals')).toHaveLength(1);
  } finally { await controls.post(gate); }
  expect((await session.api.delete(`/v1/workspaces/${session.workspaceId}`)).status()).toBe(204);
});

test('graph routing rejects disconnected and foreign agents while connected peers return through their representative', async ({ session, controls }) => {
  const marker = `graph-routing-${randomUUID()}`;
  const gate = `/control/agent-model?marker=${marker}-peer`;
  const root = await create(session.api, session.workspaceId, `${marker}-root`);
  const base = `/v1/letas/${root.id}`;
  const boxes = [];
  for (const definition of [
    { name: 'Connected box', representative: 'Graph representative', edges: [['Graph representative', 'Graph peer']], letis: [
      { name: 'Graph representative', system_prompt: `${marker}-rep` }, { name: 'Graph peer', system_prompt: `${marker}-peer` },
      { name: 'Disconnected agent', system_prompt: `${marker}-disconnected` },
    ] },
    { name: 'Foreign box', representative: 'Foreign agent', edges: [], letis: [{ name: 'Foreign agent', system_prompt: `${marker}-foreign` }] },
  ]) {
    const response = await session.api.post(`${base}/boxes`, { headers: key(), data: definition });
    expect(response.status(), await response.text()).toBe(201);
    boxes.push(await response.json());
  }
  const graph = await json(session.api, `${base}/boxes/${boxes[0].id}`);
  const rep = graph.letis.find((agent: any) => agent.name === 'Graph representative');
  const peer = graph.letis.find((agent: any) => agent.name === 'Graph peer');
  const disconnected = graph.letis.find((agent: any) => agent.name === 'Disconnected agent');
  for (const [role, responses] of Object.entries({
    root: [call('send_message', { to: 'owner', content: 'Connected graph completed safely' }), note('Graph completed')],
    rep: [call('send_message', { to: disconnected.id, content: 'Forbidden disconnected delivery' }),
      call('send_message', { to: boxes[1].representative_agent_id, content: 'Forbidden foreign delivery' }),
      call('send_message', { to: peer.id, content: 'Allowed edge by agent ID' }), note('Waiting for connected peer'),
      call('send_message', { to: boxes[0].id, content: 'Connected peer result returned through box ID' }), note('Returned through the representative')],
    peer: [call('send_message', { to: 'parent', content: 'Forbidden nonrepresentative delivery' }),
      call('send_message', { to: 'Graph representative', content: 'Allowed reply by peer name' }), note('Peer returned')],
  })) {
    expect((await controls.put('/control/agent-model', { data: { marker: `${marker}-${role}`, responses, ...(role === 'peer' ? { pause_at: 1 } : {}) } })).status()).toBe(200);
  }
  try {
    const scheduled = await session.api.post(`${base}/schedules`, { headers: key(), data: {
      box_id: boxes[0].id, title: 'Start graph', content: 'Exercise allowed graph routes', spec: { type: 'at', after_seconds: 1 },
    } });
    expect(scheduled.status(), await scheduled.text()).toBe(201);
    await expect.poll(async () => (await json(controls, gate)).blocked).toBe(true);
    await expect.poll(async () => (await json(session.api, `${base}/history?agent_id=${rep.id}&limit=100`)).items.filter((entry: any) => entry.kind === 'final_note').length).toBe(1);
    expect((await controls.post(gate)).status()).toBe(200);
    await expect.poll(async () => (await json(session.api, `${base}/messages`)).items.map((item: any) => item.content)).toContain('Connected graph completed safely');
    const repHistory = (await json(session.api, `${base}/history?agent_id=${rep.id}&limit=100`)).items;
    const peerHistory = (await json(session.api, `${base}/history?agent_id=${peer.id}&limit=100`)).items;
    expect(repHistory.filter((entry: any) => entry.kind === 'tool_result').map((entry: any) => entry.data.outcome)).toEqual(['error', 'error', 'success', 'success']);
    expect(peerHistory.filter((entry: any) => entry.kind === 'tool_result').map((entry: any) => entry.data.outcome)).toEqual(['error', 'success']);
    for (const id of [disconnected.id, boxes[1].representative_agent_id]) {
      expect((await json(session.api, `${base}/inbox?agent_id=${id}`)).items).toEqual([]);
      expect((await json(session.api, `${base}/history?agent_id=${id}`)).items).toEqual([]);
    }
    const rootInbox = (await json(session.api, `${base}/inbox`)).items;
    expect(rootInbox).toHaveLength(1);
    expect(rootInbox[0]).toMatchObject({ source_type: 'box', source_id: boxes[0].id, content: 'Connected peer result returned through box ID' });
  } finally { await controls.post(gate); }
  expect((await session.api.delete(`/v1/workspaces/${session.workspaceId}`)).status()).toBe(204);
});

test('an expiring child form and overdue child reminder remain queued across root pause and resume', async ({ session, controls }) => {
  const marker = `expiry-paused-${randomUUID()}`;
  for (const [role, responses] of Object.entries({
    root: [call('send_message', { to: 'Expiring box', content: 'Ask before continuing' }), note('Waiting for the child'),
      call('send_message', { to: 'owner', content: 'Child resumed after expiry and reminder' }), note('Expiry handled')],
    child: [call('ask_user', { title: 'Time-limited question', timeout_seconds: 10, questions: [{ type: 'text', id: 'answer', text: 'Any instructions?' }] }), note('Waiting for a timed answer'),
      call('send_message', { to: 'parent', content: 'Timed question expired; reminder also collected' }), note('Continued without a late answer')],
  })) {
    expect((await controls.put('/control/agent-model', { data: { marker: `${marker}-${role}`, responses } })).status()).toBe(200);
  }
  const root = await create(session.api, session.workspaceId, `${marker}-root`);
  const base = `/v1/letas/${root.id}`;
  const created = await session.api.post(`${base}/boxes`, { headers: key(), data: {
    name: 'Expiring box', letis: [{ name: 'Timed questioner', system_prompt: `${marker}-child` }], edges: [], representative: 'Timed questioner',
  } });
  expect(created.status(), await created.text()).toBe(201);
  const box = await created.json();
  expect((await session.api.post(`${base}/messages`, { data: { id: randomUUID(), content: 'Start timed questions' } })).status()).toBe(201);
  let ask: any;
  await expect.poll(async () => {
    ask = (await json(session.api, '/v1/human-requests?status=pending')).items.find((item: any) => item.leta_id === root.id);
    const history = (await json(session.api, `${base}/history?agent_id=${box.representative_agent_id}&limit=100`)).items;
    return Boolean(ask && history.some((entry: any) => entry.kind === 'final_note'));
  }).toBe(true);
  await expect.poll(async () => (await json(session.api, `${base}/history?limit=100`)).items.filter((entry: any) => entry.kind === 'final_note').length).toBe(1);
  expect((await session.api.post(`${base}/pause`, { headers: key() })).status()).toBe(200);
  const scheduled = await session.api.post(`${base}/schedules`, { headers: key(), data: {
    box_id: box.id, title: 'Wake paused child', content: 'Reminder queued during pause', spec: { type: 'at', after_seconds: 1 },
  } });
  expect(scheduled.status(), await scheduled.text()).toBe(201);
  const schedule = await scheduled.json();
  await expect.poll(async () => (await json(session.api, `/v1/human-requests/${ask.id}`)).status).toBe('expired');
  const childInbox = `${base}/inbox?agent_id=${box.representative_agent_id}&limit=100`;
  await expect.poll(async () => (await json(session.api, childInbox)).items.length).toBe(3);
  const before = (await json(session.api, `${base}/history?agent_id=${box.representative_agent_id}&limit=100`)).items;
  expect(before.filter((entry: any) => entry.kind === 'final_note')).toHaveLength(1);
  const late = await session.api.post(`/v1/human-requests/${ask.id}/response`, { data: { action: 'answer', answers: { answer: { text: 'Too late' } } } });
  expect(late.status(), await late.text()).toBe(200);
  expect(await late.json()).toMatchObject({ status: 'expired', decision: { action: 'expire' } });
  expect((await session.api.post(`${base}/resume`, { headers: key() })).status()).toBe(200);
  await expect.poll(async () => (await json(session.api, `${base}/messages`)).items.map((item: any) => item.content)).toContain('Child resumed after expiry and reminder');
  const childHistory = (await json(session.api, `${base}/history?agent_id=${box.representative_agent_id}&limit=100`)).items;
  const batches = childHistory.filter((entry: any) => entry.kind === 'inbox_input');
  expect(batches.map((entry: any) => [entry.data.mode, entry.data.cursor_from, entry.data.cursor_to])).toEqual([['full', 0, 1], ['full', 1, 3]]);
  expect(batches[1].data.items.map((item: any) => item.source.type).sort()).toEqual(['hitl', 'schedule']);
  const inbox = (await json(session.api, childInbox)).items;
  expect(inbox.filter((item: any) => item.source_type === 'hitl' && item.source_id === ask.id)).toHaveLength(1);
  expect(inbox.filter((item: any) => item.source_type === 'schedule' && item.source_id === schedule.id)).toHaveLength(1);
  expect((await json(session.api, `${base}/inbox`)).items.some((item: any) => item.source_type === 'hitl' && item.source_id === ask.id)).toBe(false);
  expect((await json(session.api, `/v1/human-requests/${ask.id}`)).status).toBe('expired');
  expect((await session.api.delete(`/v1/workspaces/${session.workspaceId}`)).status()).toBe(204);
});
