import { execFile } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { test, expect, mint, objectFile, inline, onboard } from '../../fixtures/api-test.ts';
import { recoveryGuide } from '../../fixtures/documents.ts';
import { control, gateway, ports, project, root, state } from '../../setup/settings.ts';

const execute = promisify(execFile);

test('coordinated recovery restores isolated metadata, exact bytes and an interrupted workflow', async ({ session, controls, identity, playwright }) => {
  test.setTimeout(600_000);
  const admission = JSON.parse(await readFile(join(state, 'environment.json'), 'utf8'));
  expect(admission).toMatchObject({ project, root, run: expect.any(String) });
  const restoredProject = `${project}-restore`;
  const recovery = join(state, 'recovery', randomUUID());
  const snapshot = join(recovery, 'snapshot');
  const restoredState = join(recovery, 'restored');
  const compose = join(root, 'infra/compose/e2e.yaml');
  const command = join(root, 'scripts/operations/recovery.py');
  const env = { ...process.env, OPENLET_E2E_ROOT: root, OPENLET_E2E_STATE: state, OPENLET_E2E_RUN: admission.run,
    OPENLET_E2E_GATEWAY_PORT: String(ports.gateway), OPENLET_E2E_CONTROL_PORT: String(ports.control), OPENLET_E2E_STORAGE_PORT: String(ports.storage) };
  const storage = await playwright.request.newContext();
  let restoredApi;
  let restoredControls;
  try {
    const guestIdentity = await (await controls.post('/control/users', { data: { email: `${randomUUID()}@example.test` } })).json();
    const guest = await onboard(controls, guestIdentity, playwright.request);
    try {
      const base = `/v1/workspaces/${session.workspaceId}`;
      const invitation = await (await session.api.post(`${base}/invitations`, { data: { email: guestIdentity.email, role: 'member' } })).json();
      expect((await guest.api.post('/v1/memberships', { data: { token: invitation.token } })).status()).toBe(201);
      expect((await guest.api.get(`/v1/filesystems/${session.filesystemId}/scopes/${session.scopeId}/nodes:resolve?path=/`)).status()).toBe(200);
      expect((await session.api.delete(`${base}/members/${guest.userId}`, {})).status()).toBe(204);
    } finally { await guest.api.dispose(); }
    const deletion = await session.api.post('/v1/workspaces', { headers: { 'idempotency-key': randomUUID() }, data: { name: 'Deleted before recovery' } });
    expect(deletion.status()).toBe(200);
    const deletedBase = `/v1/workspaces/${(await deletion.json()).id}`;
    const deletedResource = await session.api.get(deletedBase);
    const deletedFilesystem = (await deletedResource.json()).filesystem_id;
    expect((await session.api.delete(deletedBase)).status()).toBe(204);
    expect((await session.api.get(deletedBase)).status()).toBe(403);
    const personalBase = `/v1/filesystems/${session.filesystemId}/scopes/${session.personalScopeId}`;
    const personalRoot = (await (await session.api.get(`${personalBase}/nodes:resolve?path=/`)).json()).id;
    const personal = await inline({ ...session, scopeId: session.personalScopeId, rootId: personalRoot }, 'direct-grant.bin', Buffer.from('private'));
    const inlineBytes = Buffer.from([0, 255, 13, 10, 42]);
    const inlineFile = await inline(session, 'recover-inline.bin', inlineBytes);
    const marker = `restore-agent-${randomUUID()}`;
    const tool = (name: string, args: Record<string, unknown>) => ({ content: '', tool_calls: [{
      id: randomUUID(), type: 'function', function: { name, arguments: JSON.stringify(args) },
    }] });
    await inline(session, 'recovery-context.txt', Buffer.from('Recovery evidence\n' + 'context '.repeat(1250)), session.rootId, 'text/plain');
    const summary = 'Evidence was read before backup. Ask for confirmation, then continue the restored work.';
    expect((await controls.put('/control/agent-model', { data: {
      marker: 'Summarize the public working history', responses: [{ content: summary }, { content: summary }],
    } })).status()).toBe(200);
    expect((await controls.put('/control/agent-model', { data: { marker, responses: [
      tool('write_file', { path: '~/retained-home.txt', content: 'Home survives recovery' }),
      ...Array.from({ length: 9 }, () => tool('read_file', { path: '/shared/recovery-context.txt' })),
      tool('request_access', { resource: { type: 'personal_scope', user_id: session.userId }, reason: 'Resume an approved grant after recovery' }),
      tool('ask_user', { title: 'Restore confirmation', questions: [{ type: 'text', id: 'confirm', text: 'Continue after restore?' }] }),
      { content: 'Waiting for the restore confirmation' },
    ] } })).status()).toBe(200);
    const createdAgent = await session.api.post('/v1/letas', { headers: { 'idempotency-key': randomUUID() }, data: {
      workspace_id: session.workspaceId, name: 'Recovery Leta', system_prompt: marker,
      model_id: 'e2e-agent', reasoning_effort: null,
    } });
    expect(createdAgent.status(), await createdAgent.text()).toBe(201);
    const agent = await createdAgent.json();
    const agentBase = `/v1/letas/${agent.id}`;
    expect((await session.api.post(`${agentBase}/messages`, { data: { id: randomUUID(), content: 'Ask before continuing' } })).status()).toBe(201);
    let human: any;
    await expect.poll(async () => {
      human = (await (await session.api.get('/v1/human-requests?status=pending')).json()).items.find((item: any) => item.leta_id === agent.id && item.kind === 'ask');
      const history = await (await session.api.get(`${agentBase}/history?limit=100`)).json();
      return Boolean(human && history.items.some((item: any) => item.kind === 'final_note')
        && history.items.some((item: any) => item.kind === 'compaction'));
    }).toBe(true);
    expect((await session.api.post(`${agentBase}/pause`, { headers: { 'idempotency-key': randomUUID() } })).status()).toBe(200);
    const queued = { id: randomUUID(), content: 'Queued before backup' };
    expect((await session.api.post(`${agentBase}/messages`, { data: queued })).status()).toBe(201);
    const createdBox = await session.api.post(`${agentBase}/boxes`, { headers: { 'idempotency-key': randomUUID() }, data: {
      name: 'Retained box', letis: [{ name: 'Retained researcher', system_prompt: 'Remain idle' }], edges: [], representative: 'Retained researcher',
    } });
    expect(createdBox.status(), await createdBox.text()).toBe(201);
    const box = await createdBox.json();
    const createdSchedule = await session.api.post(`${agentBase}/schedules`, { headers: { 'idempotency-key': randomUUID() }, data: {
      title: 'After recovery', content: 'Continue the research', spec: { type: 'at', after_seconds: 1800 }, box_id: box.id,
    } });
    expect(createdSchedule.status(), await createdSchedule.text()).toBe(201);
    const schedule = await createdSchedule.json();
    const home = (await (await session.api.get(`/v1/workspaces/${session.workspaceId}/scopes?leta_id=${agent.id}`)).json()).items.find((item: any) => item.kind === 'home');
    const homeBase = `/v1/filesystems/${session.filesystemId}/scopes/${home.id}`;
    const homeFile = await (await session.api.get(`${homeBase}/nodes:resolve?path=/retained-home.txt`)).json();
    expect(homeFile.id).toEqual(expect.any(String));
    const checkpointSQL = ['checkpoints', 'checkpoint_blobs', 'checkpoint_writes'].map(table =>
      `SELECT '${table}',count(*),md5(string_agg(row_to_json(t)::text,'' ORDER BY row_to_json(t)::text)) FROM ${table} t WHERE thread_id='${agent.id}'`).join(';');
    const checkpointBefore = await execute('docker', ['compose', '--file', compose, '--project-name', project, 'exec', '-T', 'postgres', 'psql', '-XAt', '--set', 'ON_ERROR_STOP=1', '-U', 'openlet_admin', '-d', 'openlet_leta', '-c', checkpointSQL], { env });
    expect(Number(checkpointBefore.stdout.split('|')[1])).toBeGreaterThan(0);
    const observed = await execute('docker', ['compose', '--file', compose, '--project-name', project, 'exec', '-T', 'postgres', 'psql', '-XAt', '-U', 'openlet_admin', '-d', 'postgres', '-c',
      "SELECT coalesce(json_object_agg(datname,connections),'{}'::json) FROM (SELECT datname,count(*) AS connections FROM pg_stat_activity WHERE backend_type='client backend' GROUP BY datname) AS counts"], { env });
    const connections = JSON.parse(observed.stdout.trim()) as Record<string, number>;
    for (const database of ['account', 'workspace', 'letfs', 'leta', 'spicedb']) {
      expect(connections[`openlet_${database}`] ?? 0).toBeGreaterThan(0);
      expect(connections[`openlet_${database}`]).toBeLessThanOrEqual(16);
    }
    expect(Object.values(connections).reduce((sum, count) => sum + count, 0)).toBeLessThanOrEqual(145);
    console.log('Observed startup PostgreSQL client connections:', connections);
    const bytes = Buffer.alloc(300_000, 0x6b);
    const original = await objectFile(session, storage, 'recover-bytes.bin', bytes);
    expect((await controls.put('/control/storage', { data: { method: 'GET', contains: '/objects/', mode: 'pause' } })).status()).toBe(200);
    const documentBytes = recoveryGuide();
    const document = await objectFile(session, storage, 'recover-workflow.docx', documentBytes, session.rootId,
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document');
    await expect.poll(async () => (await (await controls.get('/control/storage')).json()).hits).toBe(1);
    const approval = (await (await session.api.get('/v1/human-requests?status=pending')).json()).items.find((item: any) => item.leta_id === agent.id && item.kind === 'approval');
    expect(approval).toBeTruthy();
    // Commit acceptance while the actual grant dependency is unavailable.
    await execute('docker', ['compose', '--file', compose, '--project-name', project, 'stop', 'workspace'], { env, timeout: 60_000 });
    const accepted = await session.api.post(`/v1/human-requests/${approval.id}/response`, { data: { action: 'accept' } });
    expect(accepted.status(), await accepted.text()).toBe(200);
    expect(await accepted.json()).toMatchObject({ status: 'resolved', decision: { action: 'accept' }, outcome: null });
    await mkdir(recovery, { recursive: true, mode: 0o700 });
    await execute('python3', [command, 'backup', '--compose', compose, '--project', project, '--state', state, '--output', snapshot], { env, timeout: 240_000 });
    const manifest = JSON.parse(await readFile(join(snapshot, 'manifest.json'), 'utf8'));
    expect(manifest).toMatchObject({ source_project: project, coordinated: true });
    expect(manifest.version).toBe(3);
    expect(manifest.databases).toEqual(['account', 'workspace', 'letfs', 'leta', 'temporal', 'temporal_visibility', 'spicedb']);
    await execute('python3', [command, 'restore', '--compose', compose, '--project', restoredProject, '--state', restoredState, '--snapshot', snapshot], { env, timeout: 120_000 });
    const restoredEnv = { ...env, OPENLET_E2E_STATE: restoredState };
    // Restore is deliberately fenced until the explicit resume command.
    const beforeResume = await execute('docker', ['compose', '--file', compose, '--project-name', restoredProject, 'ps', '--status', 'running', '--services'], { env: restoredEnv });
    expect(beforeResume.stdout.trim().split('\n')).toEqual(['postgres']);
    // Erase only this isolated projection while SpiceDB and all graph writers are stopped.
    await execute('docker', ['compose', '--file', compose, '--project-name', restoredProject, 'exec', '-T', 'postgres', 'psql', '-XAt', '--set', 'ON_ERROR_STOP=1', '-U', 'openlet_admin', '-d', 'openlet_spicedb', '-c',
      "DELETE FROM relation_tuple WHERE namespace IN ('workspace','filesystem') OR (namespace='scope' AND userset_namespace='workspace')"], { env: restoredEnv });
    await execute('docker', ['compose', '--file', compose, '--project-name', restoredProject, 'up', '--detach', '--wait', '--wait-timeout', '90', 'spicedb'], { env: restoredEnv, timeout: 120_000 });
    try {
    const empty = await execute('docker', ['compose', '--file', compose, '--project-name', restoredProject, 'exec', '-T', 'postgres', 'psql', '-XAt', '-U', 'openlet_admin', '-d', 'openlet_spicedb', '-c',
      "SELECT count(*) FROM relation_tuple WHERE namespace='workspace'"], { env: restoredEnv });
    expect(Number(empty.stdout.trim())).toBe(0);
    // Resume rebuilds Workspace-owned tuples; users have no self/owner projection.
    await execute('docker', ['compose', '--file', compose, '--project-name', restoredProject, 'stop', 'spicedb'], { env: restoredEnv });
    const interrupted = await execute('docker', ['compose', '--file', compose, '--project-name', restoredProject, 'ps', '--status', 'running', '--services'], { env: restoredEnv });
    expect(interrupted.stdout.trim().split('\n')).toEqual(['postgres']);
      await execute('python3', [command, 'resume', '--compose', compose, '--project', restoredProject, '--state', restoredState], { env: restoredEnv, timeout: 120_000 });
    } catch (error) {
      const logs = await execute('docker', ['compose', '--file', compose, '--project-name', restoredProject, 'logs', '--no-color', '--tail', '100'], { env: restoredEnv, maxBuffer: 16 * 1024 * 1024 });
      let diagnostic = logs.stdout + logs.stderr + String((error as { stdout?: string }).stdout ?? '');
      for (const file of await readdir(join(restoredState, 'secrets'))) {
        const secret = (await readFile(join(restoredState, 'secrets', file), 'utf8')).trim();
        if (secret) for (const value of [secret, encodeURIComponent(secret)]) diagnostic = diagnostic.replaceAll(value, '[REDACTED]');
      }
      await writeFile(join(state, 'restore-services.log'), diagnostic, { mode: 0o600 });
      throw error;
    }
    restoredControls = await playwright.request.newContext({ baseURL: control, extraHTTPHeaders: { authorization: `Bearer ${(await readFile(join(restoredState, 'secrets/fixture_control_token'), 'utf8')).trim()}` } });
    expect((await restoredControls.post('/control/users', { data: identity })).status()).toBe(201);
    const jwt = await mint(restoredControls, identity, { openlet_user_id: session.userId });
    restoredApi = await playwright.request.newContext({ baseURL: gateway, extraHTTPHeaders: { authorization: `Bearer ${jwt}` } });
    const base = `/v1/filesystems/${session.filesystemId}/scopes/${session.scopeId}`;
    await expect.poll(async () => {
      const responses = await Promise.all([`/v1/workspaces/${session.workspaceId}`, `${base}/nodes:resolve?path=/`]
        .map(path => restoredApi!.get(path)));
      return responses.map(response => response.status());
    }, { message: 'Workspace and filesystem routes must both recover before reading restored bytes' }).toEqual([200, 200]);
    expect(await (await restoredApi.get(`${base}/nodes/${inlineFile.id}/content`)).body()).toEqual(inlineBytes);
    expect((await restoredApi.get(`/v1/filesystems/${deletedFilesystem}`)).status()).toBe(403);
    expect((await restoredApi.get(deletedBase)).status()).toBe(403);
    expect(await (await restoredApi.get(`${personalBase}/nodes/${personal.id}/content`)).body()).toEqual(Buffer.from('private'));
    const checkpointAfter = await execute('docker', ['compose', '--file', compose, '--project-name', restoredProject, 'exec', '-T', 'postgres', 'psql', '-XAt', '--set', 'ON_ERROR_STOP=1', '-U', 'openlet_admin', '-d', 'openlet_leta', '-c', checkpointSQL], { env: restoredEnv });
    expect(checkpointAfter.stdout).toBe(checkpointBefore.stdout);
    expect(await (await restoredApi.get(agentBase)).json()).toMatchObject({ id: agent.id, status: 'active', paused: true });
    expect(await (await restoredApi.get(`${agentBase}/boxes/${box.id}`)).json()).toMatchObject({ id: box.id, status: 'active', letis: [{ name: 'Retained researcher' }] });
    expect(await (await restoredApi.get(`${agentBase}/schedules/${schedule.id}`)).json()).toMatchObject({ id: schedule.id, forecast_status: 'available' });
    expect(await (await restoredApi.get(`/v1/human-requests/${human.id}`)).json()).toMatchObject({ status: 'pending', title: 'Restore confirmation' });
    await expect.poll(async () => (await (await restoredApi!.get(`/v1/human-requests/${approval.id}`)).json()).outcome?.granted,
      { message: 'Accepted access must settle after restoring the real Workspace dependency' }).toBe(true);
    const grantedScopes = await (await restoredApi.get(`/v1/workspaces/${session.workspaceId}/scopes?leta_id=${agent.id}`)).json();
    expect(grantedScopes.items.find((item: any) => item.id === session.personalScopeId)).toMatchObject({ read_content: true, write: false });
    await expect.poll(async () => (await (await restoredApi!.get(`${agentBase}/inbox?limit=100`)).json()).items
      .filter((item: any) => item.source_type === 'hitl' && item.source_id === approval.id).length).toBe(1);
    expect(await (await restoredApi.get(`${homeBase}/nodes/${homeFile.id}/content`)).body()).toEqual(Buffer.from('Home survives recovery'));
    const historyBeforeResume = await (await restoredApi.get(`${agentBase}/history?limit=100`)).json();
    expect(historyBeforeResume.items.find((item: any) => item.kind === 'final_note').data.content).toEqual([
      { type: 'text', text: 'Waiting for the restore confirmation' },
    ]);
    expect(historyBeforeResume.items.find((item: any) => item.kind === 'compaction').data.summary).toContain(summary);
    const replay = await fetch(`${gateway}${agentBase}/events`, { signal: AbortSignal.timeout(5000), headers: {
      authorization: `Bearer ${jwt}`, 'last-event-id': '1-0',
    } });
    expect(replay.status).toBe(200);
    const reader = replay.body!.getReader();
    try {
      let frame = '';
      const decoder = new TextDecoder();
      while (!frame.includes('\n\n')) {
        const chunk = await reader.read();
        expect(chunk.done).toBe(false);
        frame += decoder.decode(chunk.value, { stream: true });
      }
      const data = frame.split('\n').find(line => line.startsWith('data: '))!;
      expect(JSON.parse(data.slice(6)).event.name).toBe('resync_required');
    } finally { await reader.cancel(); reader.releaseLock(); }
    expect((await restoredControls.put('/control/agent-model', { data: { marker, responses: [
      tool('send_message', { to: 'owner', content: 'Continued from the restored checkpoint' }), { content: 'Restored work completed' },
    ] } })).status()).toBe(200);
    expect((await restoredApi.post(`/v1/human-requests/${human.id}/response`, { data: { action: 'answer', answers: { confirm: { text: 'Continue' } } } })).status()).toBe(200);
    expect((await restoredApi.post(`${agentBase}/resume`, { headers: { 'idempotency-key': randomUUID() } })).status()).toBe(200);
    await expect.poll(async () => (await (await restoredApi!.get(`${agentBase}/messages`)).json()).items.map((item: any) => item.content)).toContain('Continued from the restored checkpoint');
    const restoredMessages = (await (await restoredApi.get(`${agentBase}/messages`)).json()).items;
    expect(restoredMessages.filter((item: any) => item.id === queued.id)).toHaveLength(1);
    expect(restoredMessages.filter((item: any) => item.content === 'Continued from the restored checkpoint')).toHaveLength(1);
    expect((await restoredControls.post('/control/users', { data: guestIdentity })).status()).toBe(201);
    const guestToken = await mint(restoredControls, guestIdentity, { openlet_user_id: guest.userId });
    const revoked = await playwright.request.newContext({ baseURL: gateway, extraHTTPHeaders: { authorization: `Bearer ${guestToken}` } });
    try {
      expect((await revoked.get(`/v1/workspaces/${session.workspaceId}`)).status()).toBe(404);
      expect((await revoked.get(`${base}/nodes:resolve?path=/`)).status()).toBe(403);
    } finally { await revoked.dispose(); }
    const content = await restoredApi.get(`${base}/nodes/${original.node_id}/content`, { maxRedirects: 0 });
    expect(content.status()).toBe(307);
    expect(await (await storage.get(content.headers().location)).body()).toEqual(bytes);
    await expect.poll(async () => {
      const response = await restoredApi!.get(`${base}/nodes/${document.node_id}/processing`);
      expect(response.status()).toBe(200);
      const processing = await response.json();
      return processing.publication_status;
    }, { timeout: 150_000 }).toBe('ready');
    const search = await restoredApi.post(`${base}/search`, { data: { query: 'ORBITAL-RECOVERY-7421' } });
    expect(search.status()).toBe(200);
    expect((await search.json()).items.map((item: { node_id: string }) => item.node_id)).toContain(document.node_id);
    expect(BigInt((await (await restoredApi.get(`/v1/filesystems/${session.filesystemId}`)).json()).used_bytes)).toBeGreaterThanOrEqual(BigInt(bytes.length + documentBytes.length));
  } finally {
    await restoredApi?.dispose();
    await restoredControls?.dispose();
    await storage.dispose();
    const targetEnv = { ...env, OPENLET_E2E_STATE: restoredState };
    const resources = await execute('docker', ['container', 'ls', '--all', '--quiet', '--filter', `label=com.docker.compose.project=${restoredProject}`]);
    if (resources.stdout.trim()) {
      const details = await execute('docker', ['container', 'inspect', ...resources.stdout.trim().split(/\s+/)]);
      for (const container of JSON.parse(details.stdout)) expect(container.Config.Labels).toMatchObject({ 'openlet.e2e.run': admission.run, 'openlet.e2e.worktree': root });
      await execute('docker', ['compose', '--file', compose, '--project-name', restoredProject, 'down', '--volumes', '--remove-orphans', '--timeout', '40'], { env: targetEnv, timeout: 120_000 });
    }
    await execute('python3', [command, 'resume', '--compose', compose, '--project', project, '--state', state], { env, timeout: 120_000 });
    expect((await controls.post('/control/users', { data: identity })).status()).toBe(201);
    const token = await mint(controls, identity, { openlet_user_id: session.userId });
    const resumed = await playwright.request.newContext({ baseURL: gateway, extraHTTPHeaders: { authorization: `Bearer ${token}` } });
    try {
      await expect.poll(async () => {
        const responses = await Promise.all(['/v1/me/onboarding', `/v1/workspaces/${session.workspaceId}`, `/v1/filesystems/${session.filesystemId}/scopes/${session.scopeId}/nodes:resolve?path=/`]
          .map(path => resumed.get(path)));
        return responses.map(response => response.status());
      }, { message: 'All owner routes must recover before the next project starts' }).toEqual([200, 200, 200]);
    } finally { await resumed.dispose(); }
    await rm(recovery, { recursive: true, force: true });
  }
});
