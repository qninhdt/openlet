import { execFile } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { test, expect, mint, onboard } from '../../fixtures/api-test.ts';
import { ownedService } from '../../fixtures/restart-service.ts';
import { root } from '../../setup/settings.ts';

const execute = promisify(execFile);

test('native gRPC uses verified identity, hides private methods and observes synchronized revocation', async ({ session, controls, identity, playwright }) => {
  const otherIdentity = await (await controls.post('/control/users', { data: { email: `${randomUUID()}@example.test` } })).json();
  const guest = await onboard(controls, otherIdentity, playwright.request);
  const { id } = await ownedService('ingest-io');
  const script = await readFile(join(root, 'e2e/fixtures/native-grpc.py'), 'utf8');
  const check = async (token: string, allowed: boolean) => {
    const command = execute('docker', ['exec', '-i', id, '/app/.venv/bin/python', '-c', script], { timeout: 45_000 });
    command.child.stdin!.end(JSON.stringify({ token, allowed, filesystem_id: session.filesystemId, node_id: session.rootId, foreign_user_id: guest.userId }));
    expect((await command).stdout).toContain('isolation passed');
  };
  try {
    await check(await mint(controls, identity), true);
    const base = `/v1/workspaces/${session.workspaceId}`;
    const invite = await (await session.api.post(`${base}/invitations`, { data: { email: otherIdentity.email, role: 'viewer' } })).json();
    expect((await guest.api.post('/v1/memberships', { data: { token: invite.token } })).status()).toBe(201);
    const token = await mint(controls, otherIdentity);
    await check(token, true);
    const current = await session.api.get(base);
    expect((await session.api.delete(`${base}/members/${guest.userId}`, { headers: { 'if-match': current.headers().etag } })).status()).toBe(204);
    await check(token, false);
  } finally { await guest.api.dispose(); }
});
