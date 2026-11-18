import { expect, test } from '@playwright/test';

const workspace = process.env.OPENLET_WEB_TEST_WORKSPACE;
const agent = process.env.OPENLET_WEB_TEST_AGENT;

for (const compact of [true, false]) {
  test(`legacy compact preference ${compact} does not change chat layout`, async ({ page }) => {
    test.skip(!workspace || !agent, 'Set OPENLET_WEB_TEST_WORKSPACE and OPENLET_WEB_TEST_AGENT');
    await page.route('**/v1/me', async (route) => {
      const response = await route.fetch();
      const account = await response.json();
      await route.fulfill({
        response,
        json: {
          ...account,
          preferences: { ...account.preferences, compactMessageActions: compact },
        },
      });
    });
    const text = 'Nội dung tin nhắn dài để kiểm tra giới hạn chiều rộng và xuống dòng. '.repeat(20);
    await page.route(`**/v1/workspaces/${workspace}/letas/${agent}/messages?*`, (route) =>
      route.fulfill({
        json: {
          items: [
            {
              id: 'layout-assistant',
              role: 'assistant',
              content: text,
              created_at: '2026-11-18T00:00:01Z',
            },
            { id: 'layout-user', role: 'user', content: text, created_at: '2026-11-18T00:00:00Z' },
          ],
          next_cursor: null,
        },
      }),
    );
    await page.route(`**/v1/workspaces/${workspace}/letas/${agent}/messages/read`, (route) =>
      route.fulfill({ json: {} }),
    );
    await page.goto(`/app/${workspace}/agents/${agent}`);
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
    await expect(
      page.getByRole('switch', { name: 'Compact message actions', exact: true }),
    ).toHaveCount(0);
    await expect(page.getByRole('switch', { name: 'Show agent steps', exact: true })).toHaveCount(
      0,
    );
    await expect(page.getByRole('switch', { name: 'Message sounds', exact: true })).toBeVisible();
  });
}
