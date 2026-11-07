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
      expect((await session.api.delete(`${base}/members/${guest.accountId}`, {})).status()).toBe(204);
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
    const observed = await execute('docker', ['compose', '--file', compose, '--project-name', project, 'exec', '-T', 'postgres', 'psql', '-XAt', '-U', 'openlet_admin', '-d', 'postgres', '-c',
      "SELECT coalesce(json_object_agg(datname,connections),'{}'::json) FROM (SELECT datname,count(*) AS connections FROM pg_stat_activity WHERE backend_type='client backend' GROUP BY datname) AS counts"], { env });
    const connections = JSON.parse(observed.stdout.trim()) as Record<string, number>;
    for (const database of ['account', 'workspace', 'letfs', 'spicedb']) {
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
    await mkdir(recovery, { recursive: true, mode: 0o700 });
    await execute('python3', [command, 'backup', '--compose', compose, '--project', project, '--state', state, '--output', snapshot], { env, timeout: 240_000 });
    const manifest = JSON.parse(await readFile(join(snapshot, 'manifest.json'), 'utf8'));
    expect(manifest).toMatchObject({ source_project: project, coordinated: true });
    expect(manifest.version).toBe(3);
    expect(manifest.databases).toEqual(['account', 'workspace', 'letfs', 'temporal', 'temporal_visibility', 'spicedb']);
    await execute('python3', [command, 'restore', '--compose', compose, '--project', restoredProject, '--state', restoredState, '--snapshot', snapshot], { env, timeout: 120_000 });
    const restoredEnv = { ...env, OPENLET_E2E_STATE: restoredState };
    // Restore is deliberately fenced until the explicit resume command.
    const beforeResume = await execute('docker', ['compose', '--file', compose, '--project-name', restoredProject, 'ps', '--status', 'running', '--services'], { env: restoredEnv });
    expect(beforeResume.stdout.trim().split('\n')).toEqual(['postgres']);
    // Erase only this isolated projection while SpiceDB and all graph writers are stopped.
    await execute('docker', ['compose', '--file', compose, '--project-name', restoredProject, 'exec', '-T', 'postgres', 'psql', '-XAt', '--set', 'ON_ERROR_STOP=1', '-U', 'openlet_admin', '-d', 'openlet_spicedb', '-c',
      "DELETE FROM relation_tuple WHERE namespace IN ('account','workspace','filesystem') OR (namespace='scope' AND userset_namespace='workspace')"], { env: restoredEnv });
    await execute('docker', ['compose', '--file', compose, '--project-name', restoredProject, 'up', '--detach', '--wait', '--wait-timeout', '90', 'spicedb'], { env: restoredEnv, timeout: 120_000 });
    try {
    await execute('docker', ['compose', '--file', compose, '--project-name', restoredProject, 'run', '--rm', '--no-deps', '--build', 'account', '--rebuild-authorization'], { env: restoredEnv, timeout: 120_000 });
    const partial = await execute('docker', ['compose', '--file', compose, '--project-name', restoredProject, 'exec', '-T', 'postgres', 'psql', '-XAt', '-U', 'openlet_admin', '-d', 'openlet_spicedb', '-c',
      "SELECT count(*) FILTER (WHERE namespace='account'),count(*) FILTER (WHERE namespace='workspace') FROM relation_tuple"], { env: restoredEnv });
    const [accounts, workspaces] = partial.stdout.trim().split('|').map(Number);
    expect(accounts).toBeGreaterThan(0);
    expect(workspaces).toBe(0);
    // Interrupt between canonical owners; resume must repeat Account and finish Workspace.
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
    const jwt = await mint(restoredControls, identity, { openlet_account_id: session.accountId });
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
    expect((await restoredControls.post('/control/users', { data: guestIdentity })).status()).toBe(201);
    const guestToken = await mint(restoredControls, guestIdentity, { openlet_account_id: guest.accountId });
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
    const token = await mint(controls, identity, { openlet_account_id: session.accountId });
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
