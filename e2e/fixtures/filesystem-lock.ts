import { execFile, spawn } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { project, root, state } from '../setup/settings.ts';

const execute = promisify(execFile);

export async function lockFilesystemRoot(filesystemId: string): Promise<() => Promise<void>> {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(filesystemId)) throw new Error('Invalid filesystem ID');
  const admission = JSON.parse(await readFile(join(state, 'environment.json'), 'utf8'));
  if (admission.project !== project || admission.root !== root || typeof admission.run !== 'string') throw new Error('Lock environment ownership mismatch');
  const found = await execute('docker', ['container', 'ls', '--quiet', '--filter', `label=com.docker.compose.project=${project}`, '--filter', 'label=com.docker.compose.service=postgres']);
  const id = found.stdout.trim();
  if (!id || /\s/.test(id)) throw new Error('Expected one owned PostgreSQL container');
  const inspected = await execute('docker', ['container', 'inspect', id]);
  const labels = JSON.parse(inspected.stdout)[0].Config.Labels;
  if (labels['openlet.e2e.run'] !== admission.run || labels['openlet.e2e.worktree'] !== root) throw new Error('Lock resource changed owner');
  const process = spawn('docker', ['exec', '--interactive', id, 'psql', '--username', 'openlet_admin', '--dbname', 'openlet_letfs',
    '--no-psqlrc', '--quiet', '--tuples-only', '--set', 'ON_ERROR_STOP=1'], { stdio: ['pipe', 'pipe', 'pipe'], timeout: 90_000 });
  let diagnostics = '';
  process.stderr.on('data', chunk => { diagnostics = (diagnostics + chunk.toString()).slice(-4000); });
  const exited = new Promise<void>((resolve, reject) => {
    process.once('error', reject);
    process.once('exit', code => code === 0 ? resolve() : reject(new Error(`Filesystem lock exited ${code}: ${diagnostics}`)));
  });
  const release = async () => {
    if (process.exitCode === null) process.stdin.end('ROLLBACK;\n\\q\n');
    await exited;
  };
  try {
    await Promise.race([new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Filesystem lock readiness timed out')), 10_000);
      let output = '';
      process.stdout.on('data', chunk => {
        output = (output + chunk.toString()).slice(-4000);
        if (output.includes('filesystem-lock-ready')) { clearTimeout(timer); resolve(); }
      });
      exited.finally(() => clearTimeout(timer)).catch(() => {});
      // Block child deletion after the owner has durably admitted filesystem cleanup.
      process.stdin.write(`BEGIN;\nSELECT n.id FROM nodes n JOIN scopes s ON s.root_id=n.id WHERE s.filesystem_id='${filesystemId}' FOR UPDATE OF n;\n\\echo filesystem-lock-ready\n`);
    }), exited.then(() => { throw new Error('Filesystem lock closed before readiness'); })]);
    return release;
  } catch (error) { await release().catch(() => {}); throw error; }
}
