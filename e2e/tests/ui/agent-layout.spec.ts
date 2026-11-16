import { expect, test, type Locator } from '@playwright/test';

async function readingPosition(viewport: Locator) {
  return viewport.evaluate(
    (el) =>
      new Promise<{ id: string; offset: number }>((resolve) => {
        requestAnimationFrame(() =>
          requestAnimationFrame(() => {
            const top = el.getBoundingClientRect().top;
            const item = Array.from(
              el.querySelectorAll<HTMLElement>('[data-slot=message-scroller-item]'),
            ).find((item) => item.dataset.messageId && item.getBoundingClientRect().bottom > top)!;
            resolve({
              id: item.dataset.messageId!,
              offset: item.getBoundingClientRect().top - top,
            });
          }),
        );
      }),
  );
}

test('only the selected tab mounts; agent drafts and transcript positions survive switching', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1452, height: 886 });
  await page.goto('/app?agent=forge');
  const chat = page.getByLabel('Forge private chat', { exact: true });
  const viewport = chat.locator('[data-slot=message-scroller-viewport]');
  const composer = page.getByRole('textbox', { name: 'Message Forge', exact: true });
  await composer.fill('Draft stays with Forge');
  await expect(page.getByLabel('Forge conversation', { exact: true })).toHaveCount(0);
  await expect(page.getByLabel('Agent overview', { exact: true })).toHaveCount(0);
  await expect(page.locator('.box-canvas')).toHaveCount(0);
  await expect.poll(() => viewport.evaluate((el) => el.scrollTop)).toBeGreaterThan(200);
  await viewport.hover();
  await page.mouse.wheel(0, -350);
  await expect
    .poll(() => viewport.evaluate((el) => el.scrollHeight - el.clientHeight - el.scrollTop))
    .toBeGreaterThan(100);
  const chatPosition = await readingPosition(viewport);

  await page.getByRole('tab', { name: 'Activity', exact: true }).click();
  await expect(chat).toHaveCount(0);
  const activity = page.getByLabel('Forge conversation', { exact: true });
  const activityViewport = activity.locator('[data-slot=message-scroller-viewport]');
  await expect.poll(() => activityViewport.evaluate((el) => el.scrollTop)).toBeGreaterThan(500);
  await activityViewport.hover();
  await page.mouse.wheel(0, -700);
  await expect
    .poll(() => activityViewport.evaluate((el) => el.scrollHeight - el.clientHeight - el.scrollTop))
    .toBeGreaterThan(100);
  const activityPosition = await readingPosition(activityViewport);

  await page.getByRole('button', { name: 'Pulse Signals', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Message Pulse', exact: true })).toHaveText('');
  await expect(activity).toHaveCount(0);
  const pulseViewport = page
    .getByLabel('Pulse private chat', { exact: true })
    .locator('[data-slot=message-scroller-viewport]');
  await expect
    .poll(() => pulseViewport.evaluate((el) => el.scrollHeight - el.clientHeight - el.scrollTop))
    .toBeLessThan(2);
  await page.getByRole('button', { name: 'Forge Builder', exact: true }).click();
  await expect(activity).toBeVisible();
  await expect
    .poll(async () => (await readingPosition(activityViewport)).id)
    .toBe(activityPosition.id);
  await expect
    .poll(async () =>
      Math.abs((await readingPosition(activityViewport)).offset - activityPosition.offset),
    )
    .toBeLessThan(3);
  await page.getByRole('tab', { name: 'Forge', exact: true }).click();
  await expect(activity).toHaveCount(0);
  await expect(composer).toHaveText('Draft stays with Forge');
  await expect.poll(async () => (await readingPosition(viewport)).id).toBe(chatPosition.id);
  await expect
    .poll(async () => Math.abs((await readingPosition(viewport)).offset - chatPosition.offset))
    .toBeLessThan(3);
  await page.getByRole('button', { name: 'Pulse Signals', exact: true }).click();
  await expect
    .poll(() => pulseViewport.evaluate((el) => el.scrollHeight - el.clientHeight - el.scrollTop))
    .toBeLessThan(2);
  const pulseComposer = page.getByRole('textbox', { name: 'Message Pulse', exact: true });
  await pulseComposer.fill('New message after restoring the end');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect
    .poll(() =>
      pulseViewport
        .getByText('New message after restoring the end', { exact: true })
        .evaluate((el) => {
          const viewport = el.closest('[data-slot=message-scroller-viewport]')!;
          const item = el.getBoundingClientRect(),
            box = viewport.getBoundingClientRect();
          return item.top >= box.top && item.bottom <= box.bottom;
        }),
    )
    .toBe(true);
});

for (const width of [390, 721, 1344, 1860]) {
  test(`chat and activity share transcript padding at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/app');
    if (width <= 720)
      await page.getByRole('button', { name: 'Atlas Assistant', exact: true }).click();
    const chat = page.getByLabel('Atlas private chat', { exact: true });
    const padding = await chat.locator('[data-slot=message-scroller-content]').evaluate((el) => {
      const style = getComputedStyle(el);
      return [
        style.paddingTop,
        style.paddingRight,
        style.paddingBottom,
        style.paddingLeft,
        style.maxWidth,
      ];
    });
    await page.getByRole('tab', { name: 'Activity', exact: true }).click();
    if (width <= 720) await page.getByRole('button', { name: 'Back to chat', exact: true }).click();
    const activity = page.getByLabel('Atlas conversation', { exact: true });
    await expect(activity).toBeVisible();
    expect(
      await activity.locator('[data-slot=message-scroller-content]').evaluate((el) => {
        const style = getComputedStyle(el);
        return [
          style.paddingTop,
          style.paddingRight,
          style.paddingBottom,
          style.paddingLeft,
          style.maxWidth,
        ];
      }),
    ).toEqual(padding);
    expect(padding).toEqual([
      '12px',
      width < 640 ? '12px' : '20px',
      '24px',
      width < 640 ? '12px' : '20px',
      '1440px',
    ]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({
      path: `../.impeccable/review/agent-chat-activity/layout-${width}.png`,
    });
  });
}

test('resizing either sidebar keeps headers aligned through tab changes and collapse', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto('/app');
  await page.getByRole('tab', { name: 'Activity', exact: true }).click();
  async function drag(name: string, delta: number) {
    const handle = page.getByRole('separator', { name, exact: true });
    const box = (await handle.boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + 100);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + delta, box.y + 100, { steps: 12 });
    await page.mouse.up();
  }
  async function aligned() {
    const sidebar = (await page.getByLabel('Agent sidebar', { exact: true }).boundingBox())!;
    const header = (await page.locator('.shell-top-navigation').boundingBox())!;
    expect(Math.abs(sidebar.width - header.width)).toBeLessThan(1);
    const panel = (await page.getByLabel('Agent side panel', { exact: true }).boundingBox())!;
    const tabs = (await page
      .getByRole('tablist', { name: 'Agent side panel tabs', exact: true })
      .locator('..')
      .locator('..')
      .boundingBox())!;
    expect(Math.abs(panel.x - tabs.x)).toBeLessThan(1);
  }
  await drag('Resize sidebar', 60);
  await drag('Resize side panel', -80);
  await aligned();
  await page.getByRole('tab', { name: 'Overview', exact: true }).click();
  await page.getByRole('tab', { name: 'Activity', exact: true }).click();
  await aligned();
  await drag('Resize sidebar', -400);
  await expect(page.getByLabel('Agent sidebar', { exact: true })).toHaveCSS('width', '88px');
  await aligned();
  const handle = page.getByRole('separator', { name: 'Resize sidebar', exact: true });
  await handle.focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByLabel('Agent sidebar', { exact: true })).not.toHaveCSS('width', '88px');
  await aligned();
});
