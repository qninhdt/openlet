import { execFile, spawn } from 'node:child_process';
import { randomBytes, randomUUID } from 'node:crypto';
import { once } from 'node:events';
import { chmod, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { control, ports, project, root, state } from './settings.ts';

const execute = promisify(execFile);

export default async function setup() {
  const lock = spawn('flock', ['--nonblock', '--no-fork', join(tmpdir(), `${project}.lock`), process.execPath,
    '-e', "process.stdout.write('locked\\n'); process.stdin.resume();"], { stdio: ['pipe', 'pipe', 'pipe'] });
  await new Promise<void>((resolve, reject) => {
    lock.once('error', reject);
    lock.once('exit', () => reject(new Error('Another API E2E run owns the environment, or flock failed')));
    lock.stdout.once('data', () => resolve());
  });

  const run = randomUUID();
  const secrets: Record<string, string> = {};
  const env = { ...process.env, OPENLET_E2E_ROOT: root, OPENLET_E2E_STATE: state, OPENLET_E2E_RUN: run,
    OPENLET_E2E_GATEWAY_PORT: String(ports.gateway), OPENLET_E2E_CONTROL_PORT: String(ports.control),
    OPENLET_E2E_STORAGE_PORT: String(ports.storage) };
  const composeArgs = ['compose', '--project-name', project, '--file', join(root, 'infra/compose/e2e.yaml')];
  let ownsEnvironment = false;
  let cleanupPromise: Promise<void> | undefined;
  const startup = new AbortController();
  let activeCommand: Promise<unknown> | undefined;

  function redact(value: string) {
    for (const secret of Object.values(secrets)) value = value.replaceAll(secret, '[REDACTED]');
    return value.replace(/(Bearer\s+)[^\s"<>]+/gi, '$1[REDACTED]')
      .replace(/(https?:\/\/[^\s"?]+)\?[^\s"]+/g, '$1?[REDACTED]');
  }

  async function docker(args: string[], timeout = 180_000, input?: string, disposing = false) {
    try {
      const command = execute('docker', args, { cwd: root, env, timeout, maxBuffer: 32 * 1024 * 1024, signal: disposing ? undefined : startup.signal });
      if (!disposing) activeCommand = command;
      if (input !== undefined) command.child.stdin?.end(input);
      const result = await command;
      return result.stdout;
    } catch (error) {
      if (!error || typeof error !== 'object') throw error;
      const output = ('stdout' in error ? String(error.stdout) : '') + ('stderr' in error ? String(error.stderr) : '');
      throw new Error(redact(`Docker command failed: ${args.join(' ')}\n${output.slice(-24_000)}`));
    } finally { if (!disposing) activeCommand = undefined; }
  }
  const compose = (args: string[], timeout?: number, input?: string, disposing = false) => docker([...composeArgs, ...args], timeout, input, disposing);

  async function resources(kind: 'container' | 'volume' | 'network', disposing = false) {
    const ids = (await docker([kind, 'ls', '-q', ...(kind === 'container' ? ['--all'] : []), '--filter', `label=com.docker.compose.project=${project}`], undefined, undefined, disposing)).trim();
    return ids ? ids.split(/\s+/) : [];
  }

  function cleanup() {
    return cleanupPromise ??= dispose();
  }

  async function dispose() {
    try {
      startup.abort();
      await activeCommand?.catch(() => {});
      if (ownsEnvironment) {
        for (const kind of ['container', 'volume', 'network'] as const) {
          const ids = await resources(kind, true);
          if (!ids.length) continue;
          const inspected = JSON.parse(await docker([kind, 'inspect', ...ids], undefined, undefined, true)) as Array<{
            Labels?: Record<string, string>; Config?: { Labels?: Record<string, string> };
          }>;
          for (const item of inspected) {
            const labels = item.Labels ?? item.Config?.Labels;
            if (labels?.['openlet.e2e.run'] !== run || labels['openlet.e2e.worktree'] !== root) {
              throw new Error('Refusing E2E cleanup: resource ownership changed');
            }
          }
        }
        try {
          await writeFile(join(state, 'services.log'), redact(await compose(['logs', '--no-color', '--tail', '300'], undefined, undefined, true)), { mode: 0o600 });
        } finally {
          await compose(['down', '--volumes', '--remove-orphans', '--timeout', '40'], undefined, undefined, true);
        }
      }
    } finally {
      if (lock.exitCode === null && lock.signalCode === null) {
        const exited = once(lock, 'exit');
        lock.stdin.end();
        await exited;
      }
      process.off('SIGINT', interrupt); process.off('SIGTERM', terminate);
    }
  }
  const interrupt = () => { void cleanup().finally(() => process.exit(130)); };
  const terminate = () => { void cleanup().finally(() => process.exit(143)); };
  process.once('SIGINT', interrupt); process.once('SIGTERM', terminate);

  async function waitFor(description: string, check: () => Promise<boolean>, timeout = 120_000) {
    const until = Date.now() + timeout;
    let lastError: unknown;
    while (Date.now() < until) {
      try { if (await check()) return; } catch (error) { lastError = error; }
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    throw new Error(`${description} did not become ready within ${timeout / 1000}s`, { cause: lastError });
  }

  try {
    for (const kind of ['container', 'volume', 'network'] as const) {
      if ((await resources(kind)).length) throw new Error(`Existing ${project} ${kind} resources require inspection/backup before a new run`);
    }
    for (const port of Object.values(ports)) {
      const listener = createServer();
      await new Promise<void>((resolve, reject) => {
        listener.once('error', () => reject(new Error(`API E2E port ${port} is occupied; no process was stopped`)));
        listener.listen(port, '127.0.0.1', () => listener.close(error => error ? reject(error) : resolve()));
      });
    }
    await mkdir(join(state, 'secrets'), { recursive: true, mode: 0o700 });
    await rm(join(state, 'histories'), { recursive: true, force: true });
    await chmod(state, 0o700);
    await chmod(join(state, 'secrets'), 0o700);
    for (const name of ['postgres_password', 'account_db_password', 'workspace_db_password', 'letfs_db_password',
      'temporal_db_password', 'temporal_visibility_db_password', 'spicedb_db_password', 'spicedb_key', 'gateway_token',
      'workspace_service_token', 'ingest_service_token', 'clerk_secret_key', 'fixture_control_token',
      'openrouter_api_key', 'qdrant_api_key', 's3_access_key_id', 's3_secret_access_key']) {
      secrets[name] = randomBytes(32).toString('base64url');
    }
    for (const app of ['account', 'workspace', 'letfs', 'spicedb']) {
      secrets[`${app}_database_url`] = `postgres://openlet_${app}:${secrets[`${app}_db_password`]}@postgres:5432/openlet_${app}`;
    }
    for (const [name, value] of Object.entries(secrets)) {
      // Nonroot containers read bind-mounted secrets; the host parent remains private.
      const path = join(state, 'secrets', name);
      await chmod(path, 0o644).catch(error => { if (error.code !== 'ENOENT') throw error; });
      await writeFile(path, value, { mode: 0o644 });
    }
    let sql = '\\set ON_ERROR_STOP on\n';
    for (const app of ['account', 'workspace', 'letfs', 'temporal', 'temporal_visibility', 'spicedb']) {
      const role = `openlet_${app}`;
      sql += `CREATE ROLE ${role} LOGIN PASSWORD '${secrets[`${app}_db_password`]}';\n`;
      sql += `ALTER ROLE ${role} SET statement_timeout = '15s';\nALTER ROLE ${role} SET lock_timeout = '5s';\n`;
      sql += `CREATE DATABASE ${role} OWNER ${role};\nREVOKE ALL ON DATABASE ${role} FROM PUBLIC;\n`;
    }
    await writeFile(join(state, 'init.sql'), sql, { mode: 0o644 });
    await writeFile(join(state, 'spicedb.env'),
      `SPICEDB_DATASTORE_ENGINE=postgres\nSPICEDB_DATASTORE_CONN_URI=${secrets.spicedb_database_url}?sslmode=disable\nSPICEDB_GRPC_PRESHARED_KEY=${secrets.spicedb_key}\n`,
      { mode: 0o644 });
    const temporal = JSON.parse(await readFile(join(root, 'infra/config/temporal.template.json'), 'utf8'));
    temporal.persistence.datastores.default.sql.password = secrets.temporal_db_password;
    temporal.persistence.datastores.visibility.sql.password = secrets.temporal_visibility_db_password;
    await writeFile(join(state, 'temporal.json'), JSON.stringify(temporal), { mode: 0o644 });
    const envoy = JSON.parse((await readFile(join(root, 'infra/config/envoy.template.json'), 'utf8'))
      .replaceAll('__GATEWAY_TOKEN__', secrets.gateway_token).replaceAll('__JWT_ISSUER__', 'http://boundary:8080')
      .replaceAll('__JWT_AUDIENCE__', 'openlet-e2e').replace('http://jwks.invalid/__JWKS_URL__', 'http://boundary:8080/.well-known/jwks.json'));
    const jwks = envoy.static_resources.clusters.find((cluster: { name: string }) => cluster.name === 'jwks');
    jwks.load_assignment.endpoints[0].lb_endpoints[0].endpoint.address.socket_address = { address: 'boundary', port_value: 8080 };
    await writeFile(join(state, 'envoy.json'), JSON.stringify(envoy), { mode: 0o644 });

    await compose(['config', '--quiet']);
    console.log('API E2E: building current application sources');
    try {
      await writeFile(join(state, 'build.log'), redact(await compose(['--profile', 'setup', 'build'], 1_800_000)), { mode: 0o600 });
    } catch (error) {
      await writeFile(join(state, 'build.log'), String(error), { mode: 0o600 });
      throw error;
    }
    ownsEnvironment = true;
    await compose(['up', '--detach', '--wait', '--wait-timeout', '120', 'postgres', 'storage', 'qdrant', 'boundary']);
    await compose(['up', '--detach', '--wait', '--wait-timeout', '120', 'spicedb']);
    await compose(['run', '--rm', '--no-deps', 'authz-schema']);
    await compose(['up', '--detach', 'temporal']);
    for (const app of ['account', 'workspace', 'letfs']) await compose(['run', '--rm', `${app}-migrate`]);
    await waitFor('Temporal', async () => {
      try { await compose(['run', '--rm', '--no-deps', 'temporal-init', 'operator', 'cluster', 'health'], 15_000); return true; }
      catch { return false; }
    });
    await compose(['run', '--rm', '--no-deps', 'temporal-init']);
    await compose(['exec', '--no-TTY', 'storage', 'curl', '--fail', '--silent', '--show-error',
      '--aws-sigv4', 'aws:amz:us-east-1:s3', '--config', '-', '--request', 'PUT', 'http://127.0.0.1:9000/openlet-e2e'],
    30_000, `user = "${secrets.s3_access_key_id}:${secrets.s3_secret_access_key}"\n`);
    await compose(['up', '--detach', '--wait', '--wait-timeout', '120', 'account', 'workspace', 'letfs', 'ingest-cpu', 'ingest-io', 'envoy']);
    await waitFor('External-boundary fixtures', async () => {
      try { return (await fetch(`${control}/live`, { signal: AbortSignal.timeout(3000) })).ok; }
      catch { return false; }
    });
    const controlHeaders = { authorization: `Bearer ${secrets.fixture_control_token}`, 'content-type': 'application/json' };
    const identityResponse = await fetch(`${control}/control/users`, { method: 'POST', headers: controlHeaders,
      body: JSON.stringify({ email: `${run}@example.test` }), signal: AbortSignal.timeout(3000) });
    if (identityResponse.status !== 201) throw new Error('Gateway readiness identity could not be created');
    const identity = await identityResponse.json();
    const tokenResponse = await fetch(`${control}/control/token`, { method: 'POST', headers: controlHeaders,
      body: JSON.stringify({ subject: identity.id, claims: { openlet_account_id: randomUUID() } }), signal: AbortSignal.timeout(3000) });
    if (!tokenResponse.ok) throw new Error('Gateway readiness JWT could not be minted');
    const { token } = await tokenResponse.json();
    await waitFor('Gateway upstream routing', async () => {
      const headers = { authorization: `Bearer ${token}` };
      const responses = await Promise.all(['/v1/me', '/v1/workspaces'].map(path =>
        fetch(`http://127.0.0.1:${ports.gateway}${path}`, { headers, signal: AbortSignal.timeout(3000) })));
      for (const response of responses) await response.body?.cancel();
      return responses[0].status === 404 && responses[1].status === 200;
    });
    await writeFile(join(state, 'environment.json'), JSON.stringify({ project, run, root }), { mode: 0o600 });
    console.log('API E2E: real services ready');
    return cleanup;
  } catch (error) {
    await cleanup();
    throw error;
  }
}
