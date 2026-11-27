import { agent, expect, test, workspace } from '../fixtures/browser';

for (const compact of [true, false]) {
  test(`legacy compact preference ${compact} does not change chat layout`, async ({ page }) => {
    const text = 'Nội dung tin nhắn dài để kiểm tra giới hạn chiều rộng và xuống dòng. '.repeat(20);
    await page.route(`**/v1/workspaces/${workspace}/conversations/*/messages?*`, (route) =>
      route.fulfill({
        json: {
          messages: [
            {
              id: 'layout-user',
              conversationId: `conv-${agent}`,
              seq: 1,
              senderType: 'user',
              senderId: 'preview-owner',
              content: text,
              createdAt: '2026-11-18T00:00:00Z',
            },
            {
              id: 'layout-assistant',
              conversationId: `conv-${agent}`,
              seq: 2,
              senderType: 'agent',
              senderId: agent,
              content: text,
              createdAt: '2026-11-18T00:00:01Z',
            },
          ],
          hasBefore: false,
          hasAfter: false,
        },
      }),
    );
    await page.route(`**/v1/workspaces/${workspace}/conversations/*:markRead`, (route) =>
      route.fulfill({ json: { lastReadSeq: 2 } }),
    );
    await page.goto(`/app/${workspace}/agents/${agent}?compact=${compact}`);
    for (const width of [1851, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const role of ['assistant', 'user']) {
        const message = page.locator(`#chat-${role}-layout-${role}`);
        const bubble = message.locator('[data-slot=bubble-content]');
        await expect(bubble).toBeVisible();
        const bounds = await bubble.boundingBox();
        expect(bounds!.width).toBeLessThanOrEqual(720);
        if (width === 1851) expect(bounds!.width).toBeGreaterThan(650);
        expect(bounds!.x).toBeGreaterThanOrEqual(0);
        expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
        const shell = page.locator('[data-slot=message-action-shell]').filter({ has: message });
        await expect(shell).toHaveCSS('flex-direction', role === 'user' ? 'row-reverse' : 'row');
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(
        false,
      );
      await page.screenshot({ path: `/tmp/message-layout-${compact}-${width}.png` });
    }
    await page.setViewportSize({ width: 1851, height: 1000 });
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'General', exact: true })).toBeVisible();
    await expect(page.getByRole('switch', { name: 'Message sounds', exact: true })).toBeVisible();
  });
}
