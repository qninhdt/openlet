import { expect, test, type Locator, type Page } from '@playwright/test';

const picture = (avatar: Locator) => avatar.locator('svg').innerHTML();
async function expectPaused(avatar: Locator, page: Page) {
  await expect
    .poll(async () => {
      const before = await picture(avatar);
      await page.waitForTimeout(180); // Sample across several 30fps frames.
      return before === (await picture(avatar));
    })
    .toBe(true);
}

test('idle avatars animate on the whole row and keyboard focus, then settle', async ({ page }) => {
  await page.goto('/app');
  const row = page.getByRole('button', { name: 'Scout Research', exact: true });
  const avatar = row.locator('[data-avatar]');
  await expect(avatar).toBeVisible();
  await page.mouse.move(0, 0);
  await expectPaused(avatar, page);
  const still = await picture(avatar);
  await row.getByText('Scout', { exact: true }).hover();
  await expect.poll(() => picture(avatar)).not.toBe(still);
  await expect(avatar).toHaveAttribute('data-shape', 'galet');
  await page.mouse.move(0, 0);
  await expectPaused(avatar, page);
  const resting = await picture(avatar);
  await page.keyboard.press('Tab');
  await row.focus();
  await expect.poll(() => picture(avatar)).not.toBe(resting);
});

test('working avatars animate in sidebar and tab, pause while hidden and resume', async ({
  page,
}) => {
  await page.goto('/app');
  await page.mouse.move(0, 0);
  const sidebar = page
    .getByRole('button', { name: 'Atlas Assistant', exact: true })
    .locator('[data-avatar]');
  const tab = page.getByRole('tab', { name: 'Atlas', exact: true }).locator('[data-avatar]');
  for (const avatar of [sidebar, tab]) {
    await expect(avatar).toHaveAttribute('data-working', 'true');
    const before = await picture(avatar);
    await expect.poll(() => picture(avatar)).not.toBe(before);
  }
  const eyeShapes = () =>
    sidebar
      .locator('mask path')
      .evaluateAll((paths) => paths.slice(1).map((path) => path.getAttribute('d')));
  const eyes = await eyeShapes();
  await expect.poll(eyeShapes, { timeout: 8000 }).not.toEqual(eyes);
  await expect(sidebar).toHaveAttribute('data-shape', 'hexagone');
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expectPaused(sidebar, page);
  const paused = await picture(sidebar);
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect.poll(() => picture(sidebar)).not.toBe(paused);
});

test('reduced motion stays still and reacts to a preference change', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/app');
  const row = page.getByRole('button', { name: 'Atlas Assistant', exact: true });
  const avatar = row.locator('[data-avatar]');
  await expect(avatar).toBeVisible();
  await row.getByText('Atlas', { exact: true }).hover();
  await expectPaused(avatar, page);
  const still = await picture(avatar);
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await expect.poll(() => picture(avatar)).not.toBe(still);
});
