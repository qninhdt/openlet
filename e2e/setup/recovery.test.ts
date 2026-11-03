import test from 'node:test';
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { promisify } from 'node:util';
import setup from './environment.ts';
import { ports, project, root, state } from './settings.ts';

const execute = promisify(execFile);

test('operations restore real database state and S3 bytes into an isolated fenced project', { timeout: 600_000 }, async () => {
  const cleanup = await setup();
  const admission = JSON.parse(await readFile(join(state, 'environment.json'), 'utf8'));
  const env = { ...process.env, OPENLET_E2E_ROOT: root, OPENLET_E2E_STATE: state, OPENLET_E2E_RUN: admission.run,
    OPENLET_E2E_GATEWAY_PORT: String(ports.gateway), OPENLET_E2E_CONTROL_PORT: String(ports.control), OPENLET_E2E_STORAGE_PORT: String(ports.storage) };
  const compose = join(root, 'infra/compose/e2e.yaml');
  const command = join(root, 'scripts/operations/recovery.py');
  const recoveredProject = `${project}-restore`;
  const folder = join(state, 'recovery', randomUUID());
  const snapshot = join(folder, 'snapshot');
  const restored = join(folder, 'restored');
  const restoredEnv = { ...env, OPENLET_E2E_STATE: restored };
  const bytes = Buffer.from([0, 255, 23, 42, 0, 13, 10]);
  const credentials = `${(await readFile(join(state, 'secrets/s3_access_key_id'), 'utf8')).trim()}:${(await readFile(join(state, 'secrets/s3_secret_access_key'), 'utf8')).trim()}`;
  const url = `http://127.0.0.1:${ports.storage}/openlet-e2e/operations-recovery.bin`;
  try {
    await mkdir(folder, { recursive: true, mode: 0o700 });
    const payload = join(folder, 'payload.bin');
    await writeFile(payload, bytes, { mode: 0o600 });
    const send = execute('curl', ['--config', '-', '--silent', '--show-error', '--fail', '--aws-sigv4', 'aws:amz:us-east-1:s3', '--upload-file', payload, url], { timeout: 15_000 });
    send.child.stdin?.end(`user = "${credentials}"\n`);
    await send;
    const id = randomUUID();
    await execute('docker', ['compose', '--file', compose, '--project-name', project, 'exec', '-T', 'postgres', 'psql', '-X', '--set', 'ON_ERROR_STOP=1', '-U', 'openlet_admin', '-d', 'openlet_letfs', '-c', `INSERT INTO quota_buckets(id,creator_service,create_fingerprint,limit_bytes) VALUES('${id}','recovery-test',repeat('0',64),12345)`], { env });
    for (const app of ['account', 'workspace', 'letfs']) {
      await execute('docker', ['compose', '--file', compose, '--project-name', project, 'run', '--rm', `${app}-migrate`], { env });
    }
    await execute('python3', [command, 'backup', '--compose', compose, '--project', project, '--state', state, '--output', snapshot], { env, timeout: 240_000 });
    const manifest = JSON.parse(await readFile(join(snapshot, 'manifest.json'), 'utf8'));
    assert.equal(manifest.version, 3);
    assert.deepEqual(manifest.databases, ['account', 'workspace', 'letfs', 'temporal', 'temporal_visibility', 'spicedb']);
    await execute('python3', [command, 'restore', '--compose', compose, '--project', recoveredProject, '--state', restored, '--snapshot', snapshot], { env, timeout: 120_000 });
    const running = await execute('docker', ['compose', '--file', compose, '--project-name', recoveredProject, 'ps', '--status', 'running', '--services'], { env: restoredEnv });
    assert.deepEqual(running.stdout.trim().split('\n'), ['postgres']);
    const query = await execute('docker', ['compose', '--file', compose, '--project-name', recoveredProject, 'exec', '-T', 'postgres', 'psql', '-XAt', '-U', 'openlet_letfs', '-d', 'openlet_letfs', '-c', `SELECT limit_bytes FROM quota_buckets WHERE id='${id}'`], { env: restoredEnv });
    assert.equal(query.stdout.trim(), '12345');
    const restoreMarker = join(restored, 'restore.json');
    const repaired = await readFile(restoreMarker, 'utf8');
    assert.equal(JSON.parse(repaired).authorization, 'transaction-ids-repaired');
    await writeFile(restoreMarker, JSON.stringify({ ...JSON.parse(repaired), authorization: undefined }));
    await assert.rejects(execute('python3', [command, 'resume', '--compose', compose, '--project', recoveredProject, '--state', restored], { env: restoredEnv, timeout: 150_000 }), /verified datastore repair/);
    const fenced = await execute('docker', ['compose', '--file', compose, '--project-name', recoveredProject, 'ps', '--status', 'running', '--services'], { env: restoredEnv });
    assert.deepEqual(fenced.stdout.trim().split('\n'), ['postgres']);
    await writeFile(restoreMarker, repaired);
    await execute('python3', [command, 'resume', '--compose', compose, '--project', recoveredProject, '--state', restored], { env: restoredEnv, timeout: 150_000 });
    const receive = execute('curl', ['--config', '-', '--silent', '--show-error', '--fail', '--aws-sigv4', 'aws:amz:us-east-1:s3', url], { encoding: 'buffer', timeout: 15_000 });
    receive.child.stdin?.end(`user = "${credentials}"\n`);
    const received = await receive;
    assert.deepEqual(received.stdout, bytes);
    const dump = join(snapshot, 'account.dump');
    const original = await readFile(dump);
    await writeFile(dump, Buffer.from('corrupt snapshot'));
    await assert.rejects(execute('python3', [command, 'restore', '--compose', compose, '--project', `${project}-invalid`, '--state', join(folder, 'invalid'), '--snapshot', snapshot], { env, timeout: 30_000 }), /integrity/);
    await writeFile(dump, original);
  } finally {
    const ids = await execute('docker', ['container', 'ls', '--all', '--quiet', '--filter', `label=com.docker.compose.project=${recoveredProject}`]);
    if (ids.stdout.trim()) {
      const details = await execute('docker', ['container', 'inspect', ...ids.stdout.trim().split(/\s+/)]);
      for (const item of JSON.parse(details.stdout)) {
        assert.equal(item.Config.Labels['openlet.e2e.run'], admission.run);
        assert.equal(item.Config.Labels['openlet.e2e.worktree'], root);
      }
      await execute('docker', ['compose', '--file', compose, '--project-name', recoveredProject, 'down', '--volumes', '--remove-orphans', '--timeout', '40'], { env: restoredEnv, timeout: 120_000 });
    }
    await cleanup();
    await rm(folder, { recursive: true, force: true });
  }
});
