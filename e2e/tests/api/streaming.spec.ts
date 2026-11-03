import { test, expect, directory, objectFile, mint } from '../../fixtures/api-test.ts';
import { gateway } from '../../setup/settings.ts';

test('disconnecting a ZIP request cancels its pending S3 read', async ({ session, controls, identity, playwright }) => {
  const folder = await directory(session, 'cancel-archive');
  const storage = await playwright.request.newContext();
  const controller = new AbortController();
  let transfer: Promise<void> | undefined;
  try {
    await objectFile(session, storage, 'data.bin', Buffer.alloc(300_000, 0x61), folder.id);
    expect((await controls.put('/control/storage', { data: { method: 'GET', contains: '/objects/', mode: 'pause' } })).status()).toBe(200);
    const token = await mint(controls, identity);
    transfer = fetch(`${gateway}/v1/filesystems/${session.filesystemId}/nodes/${folder.id}/archive`, {
      headers: { authorization: `Bearer ${token}` }, signal: controller.signal,
    }).then(async response => { await response.arrayBuffer(); });
    // Observe the rejection immediately, while retaining it for the cancellation assertion.
    void transfer.catch(() => {});
    await expect.poll(async () => (await (await controls.get('/control/storage')).json()).active).toBe(1);
    controller.abort();
    await expect(transfer).rejects.toThrow();
    await expect.poll(async () => (await (await controls.get('/control/storage')).json()).active).toBe(0);
  } finally {
    controller.abort();
    await transfer?.catch(() => {});
    await controls.delete('/control/storage');
    await storage.dispose();
  }
});

test('S3 read failure aborts ZIP delivery instead of completing an archive with missing files', async ({ session, controls, identity, playwright }) => {
  const folder = await directory(session, 'failed-archive');
  const storage = await playwright.request.newContext();
  try {
    await objectFile(session, storage, 'data.bin', Buffer.alloc(300_000, 0x62), folder.id);
    expect((await controls.put('/control/storage', { data: { method: 'GET', contains: '/objects/', mode: 'fail', count: 100 } })).status()).toBe(200);
    const token = await mint(controls, identity);
    const outcome = await fetch(`${gateway}/v1/filesystems/${session.filesystemId}/nodes/${folder.id}/archive`, {
      headers: { authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(150_000),
    }).then(async response => {
      if (response.status !== 200) { expect(response.status).toBe(503); return 'problem'; }
      try { await response.arrayBuffer(); return 'completed'; } catch { return 'aborted'; }
    }, () => 'aborted');
    expect(['problem', 'aborted']).toContain(outcome);
    expect((await (await controls.get('/control/storage')).json()).hits).toBeGreaterThan(0);
  } finally { await controls.delete('/control/storage'); await storage.dispose(); }
});
