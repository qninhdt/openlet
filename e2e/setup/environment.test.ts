import assert from 'node:assert/strict';
import { execFile, spawn } from 'node:child_process';
import { once } from 'node:events';
import { createServer } from 'node:net';
import { promisify } from 'node:util';
import { test } from 'node:test';
import setup from './environment.ts';
import { ports, project, root } from './settings.ts';

const execute = promisify(execFile);

async function projectResources() {
  const values = await Promise.all(['container', 'volume', 'network'].map(async kind => {
    const result = await execute('docker', [kind, 'ls', '--quiet', ...(kind === 'container' ? ['--all'] : []), '--filter', `label=com.docker.compose.project=${project}`]);
    return result.stdout.trim();
  }));
  return values.filter(Boolean);
}

test('occupied ports fail without changing project resources and release the OS lock', async () => {
  assert.deepEqual(await projectResources(), [], 'another environment already owns this project');
  const listener = createServer();
  listener.listen(ports.gateway, '127.0.0.1');
  await once(listener, 'listening');
  try {
    for (let attempt = 0; attempt < 2; attempt++) {
      await assert.rejects(setup(), /port 18200 is occupied/);
      assert.deepEqual(await projectResources(), []);
    }
  } finally { listener.close(); await once(listener, 'close'); }
});

test('SIGTERM during real SpiceDB startup cleans owned resources', { timeout: 180_000 }, async () => {
  assert.deepEqual(await projectResources(), [], 'refusing to disturb another environment');
  const child = spawn(process.execPath, ['--input-type=module', '-e',
    "import setup from './e2e/setup/environment.ts'; const cleanup = await setup(); await cleanup();"],
  { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  const exit = once(child, 'exit');
  let diagnostic = '';
  child.stdout.on('data', chunk => { diagnostic = (diagnostic + chunk).slice(-8000); });
  child.stderr.on('data', chunk => { diagnostic = (diagnostic + chunk).slice(-8000); });
  try {
    const until = Date.now() + 120_000;
    while (Date.now() < until) {
      if (child.exitCode !== null || child.signalCode !== null) throw new Error(`Setup exited before the injection point: ${diagnostic}`);
      const found = await execute('docker', ['container', 'ls', '--quiet', '--filter', `label=com.docker.compose.project=${project}`,
        '--filter', 'label=com.docker.compose.service=spicedb', '--filter', 'health=starting']);
      if (found.stdout.trim()) break;
      await new Promise(resolve => setTimeout(resolve, 250));
    }
    const found = await execute('docker', ['container', 'ls', '--quiet', '--filter', `label=com.docker.compose.project=${project}`,
      '--filter', 'label=com.docker.compose.service=spicedb', '--filter', 'health=starting']);
    assert.ok(found.stdout.trim(), 'startup never reached SpiceDB readiness wait');
    child.kill('SIGTERM');
    const [code, signal] = await exit;
    assert.equal(signal, null, diagnostic);
    assert.equal(code, 143, diagnostic);
    assert.deepEqual(await projectResources(), []);
  } finally {
    if (child.exitCode === null && child.signalCode === null) { child.kill('SIGTERM'); await exit; }
  }
});
