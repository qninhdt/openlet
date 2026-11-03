import { execFile } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { ports, project, root, state } from '../setup/settings.ts';

const execute = promisify(execFile);

export async function ownedService(service: 'letfs' | 'ingest-cpu' | 'ingest-io') {
  const admission = JSON.parse(await readFile(join(state, 'environment.json'), 'utf8'));
  if (admission.project !== project || admission.root !== root || typeof admission.run !== 'string') throw new Error('E2E restart ownership mismatch');
  const { stdout } = await execute('docker', ['container', 'ls', '--all', '--quiet', '--filter', `label=com.docker.compose.project=${project}`, '--filter', `label=com.docker.compose.service=${service}`]);
  const id = stdout.trim();
  if (!id || /\s/.test(id)) throw new Error('Expected exactly one owned service container');
  const inspect = await execute('docker', ['container', 'inspect', id]);
  const labels = JSON.parse(inspect.stdout)[0].Config.Labels;
  if (labels['openlet.e2e.run'] !== admission.run || labels['openlet.e2e.worktree'] !== root) throw new Error('E2E restart resource changed owner');
  return { id, admission };
}

export async function restartService(service: 'letfs' | 'ingest-cpu' | 'ingest-io') {
  const { admission } = await ownedService(service);
  await execute('docker', ['compose', '--project-name', project, '--file', join(root, 'infra/compose/e2e.yaml'), 'restart', service], {
    cwd: root, timeout: 90_000, env: { ...process.env, OPENLET_E2E_ROOT: root, OPENLET_E2E_STATE: state, OPENLET_E2E_RUN: admission.run,
      OPENLET_E2E_GATEWAY_PORT: String(ports.gateway), OPENLET_E2E_CONTROL_PORT: String(ports.control), OPENLET_E2E_STORAGE_PORT: String(ports.storage) },
  });
}
