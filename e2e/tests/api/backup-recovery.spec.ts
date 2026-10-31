import { execFile } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { test, expect, mint, objectFile } from '../../fixtures/api-test.ts';
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
    expect(manifest.databases).toEqual(['account', 'workspace', 'letfs', 'temporal', 'temporal_visibility']);
    await execute('python3', [command, 'restore', '--compose', compose, '--project', restoredProject, '--state', restoredState, '--snapshot', snapshot], { env, timeout: 120_000 });
    const restoredEnv = { ...env, OPENLET_E2E_STATE: restoredState };
    // Restore is deliberately fenced until the explicit resume command.
    const beforeResume = await execute('docker', ['compose', '--file', compose, '--project-name', restoredProject, 'ps', '--status', 'running', '--services'], { env: restoredEnv });
    expect(beforeResume.stdout.trim().split('\n')).not.toContain('workspace');
    try {
      await execute('python3', [command, 'resume', '--compose', compose, '--project', restoredProject, '--state', restoredState], { env: restoredEnv, timeout: 120_000 });
    } catch (error) {
      const logs = await execute('docker', ['compose', '--file', compose, '--project-name', restoredProject, 'logs', '--no-color', '--tail', '100'], { env: restoredEnv, maxBuffer: 16 * 1024 * 1024 });
      let diagnostic = logs.stdout + logs.stderr;
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
    const base = `/v1/workspaces/${session.workspaceId}`;
    await expect.poll(async () => (await restoredApi!.get(base)).status()).toBe(200);
    const content = await restoredApi.get(`${base}/nodes/${original.node_id}/content`, { maxRedirects: 0 });
    expect(content.status()).toBe(307);
    expect(await (await storage.get(content.headers().location)).body()).toEqual(bytes);
    await expect.poll(async () => {
      const response = await restoredApi!.get(`${base}/nodes/${document.node_id}/processing`);
      expect(response.status()).toBe(200);
      const processing = await response.json();
      return [processing.publication_status, processing.index_status];
    }, { timeout: 150_000 }).toEqual(['ready', 'ready']);
    expect(BigInt((await (await restoredApi.get(`${base}/storage`)).json()).used_bytes)).toBeGreaterThanOrEqual(BigInt(bytes.length + documentBytes.length));
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
    const token = await mint(controls, identity);
    const resumed = await playwright.request.newContext({ baseURL: gateway, extraHTTPHeaders: { authorization: `Bearer ${token}` } });
    try {
      await expect.poll(async () => (await resumed.get('/v1/me/onboarding')).status(),
        { message: 'The resumed source gateway must route before the next project starts' }).toBe(200);
    } finally { await resumed.dispose(); }
    await rm(recovery, { recursive: true, force: true });
  }
});
