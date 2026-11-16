import { expect, test } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';

test('desktop shell navigates, isolates workspace selection and follows browser history', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/app');
  await expect(page.getByRole('heading', { name: 'Atlas', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /Workflows|Marketplace|Computer/ })).toHaveCount(0);
  await expect(page.getByRole('main')).not.toContainText('Messages will appear');
  await expect(page.getByRole('textbox', { name: 'Message Atlas', exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Hide sidebar' }).click();
  await expect(page.getByRole('complementary', { name: 'Agent sidebar' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Show sidebar' }).click();
  await page.keyboard.press('Control+k');
  await page.getByRole('combobox').fill('Forge');
  await page.getByRole('option', { name: /Forge/ }).click();
  await expect(page.getByRole('heading', { name: 'Forge', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Go back', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Atlas', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Go forward', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Forge', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Forge', exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Switch workspace', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Team workspace' }).click();
  await expect(page.getByRole('heading', { name: 'Sage', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /Forge/ })).toHaveCount(0);
  await page.getByRole('button', { name: 'Storage', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Personal', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Schedule', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Schedule', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'General', exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test('invalid URL selections fall back to an agent belonging to the selected workspace', async ({
  page,
}) => {
  await page.goto('/app?workspace=team&agent=forge&view=unknown');
  await expect(page.getByRole('heading', { name: 'Sage', exact: true })).toBeVisible();
  await page.goto('/app?workspace=%7B%7D&agent=%5B1%5D&view=%5B%5D');
  await expect(page.getByRole('heading', { name: 'Atlas', exact: true })).toBeVisible();
});

for (const width of [390, 720, 721, 1200]) {
  test(`shell, contextual panel and theme work at ${width}px`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.setViewportSize({ width, height: 762 });
    await page.goto('/app');
    if (width <= 720) {
      await expect(page.getByRole('button', { name: /Atlas Assistant/ })).toBeVisible();
      await expect(
        page.getByRole('navigation', { name: 'Workspace navigation', exact: true }),
      ).toBeVisible();
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Workspace', exact: true })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
    } else await expect(page.getByRole('heading', { name: 'Atlas', exact: true })).toBeVisible();
    await expect(page.locator('[data-avatar=bloub]').first()).toBeVisible();
    const agentRow = page.getByRole('button', { name: /Atlas Assistant/ });
    expect((await agentRow.boundingBox())!.height).toBe(width === 721 ? 60 : 102);
    expect((await agentRow.locator('[data-avatar=bloub]').boundingBox())!.width).toBe(
      width === 721 ? 48 : 56,
    );
    if (width !== 721)
      await expect(agentRow.getByText('Atlas', { exact: true })).toHaveCSS('font-size', '13px');
    await expect(
      page
        .getByRole('navigation', { name: 'Workspace navigation', exact: true })
        .getByRole('button', { name: 'Agents', exact: true })
        .locator('svg'),
    ).toHaveCSS('width', '20px');
    const screenshotDir = process.env.OPENLET_SHELL_SCREENSHOTS;
    if (screenshotDir) {
      await mkdir(screenshotDir, { recursive: true });
      await page.screenshot({
        animations: 'disabled',
        path: resolve(
          screenshotDir,
          `${width === 390 ? 'mobile' : width === 1200 ? 'desktop' : 'tablet'}.png`,
        ),
      });
    }
    if (width <= 720) {
      await expect(page.getByRole('navigation', { name: 'Mobile pane navigation' })).toBeVisible();
      if (screenshotDir)
        await page.screenshot({
          animations: 'disabled',
          path: resolve(screenshotDir, 'mobile-navigation.png'),
        });
      await page.getByRole('button', { name: /Forge Builder/ }).click();
      await expect(page.getByRole('button', { name: 'Chat', exact: true })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
      await expect(
        page.getByRole('navigation', { name: 'Workspace navigation', exact: true }),
      ).toHaveCount(0);
    }
    await expect(page.getByRole('button', { name: 'Toggle side panel' })).toBeDisabled();
    await page
      .getByRole('button', { name: /^Open (Launch plan\.md|release\.ts)$/ })
      .first()
      .click();
    await expect(
      page.getByRole('tab', { name: /^(Launch plan\.md|release\.ts)$/ }),
    ).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('tab', { name: 'Agent settings', exact: true })).toHaveCount(0);
    if (width > 720) {
      const handle = page.getByRole('separator', { name: 'Resize side panel' });
      await handle.focus();
      await page.keyboard.press('ArrowLeft');
      const bounds = await page.getByRole('button', { name: 'Close side panel' }).boundingBox();
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    }
    if (screenshotDir)
      await page.screenshot({
        animations: 'disabled',
        path: resolve(screenshotDir, `panel-${width}.png`),
      });
    await page.getByRole('button', { name: 'Close side panel' }).click();
    if (width <= 720) await page.getByRole('button', { name: 'Workspace', exact: true }).click();
    await page.getByRole('button', { name: 'Switch to light theme' }).click();
    await expect(page.locator('html')).not.toHaveClass(/dark/);
    await page.reload();
    await expect(page.locator('html')).not.toHaveClass(/dark/);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    expect(errors).toEqual([]);
  });
}

for (const width of [390, 1202, 1452]) {
  test(`settings layout and browser preferences at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 762 });
    await page.goto('/app?view=settings');
    await expect(page.getByRole('heading', { name: 'General', exact: true })).toBeVisible();
    const toggle = page.getByRole('switch', { name: 'Show agent steps', exact: true });
    await toggle.click();
    await page.reload();
    await expect(toggle).toBeChecked();
    const screenshotDir = process.env.OPENLET_SHELL_SCREENSHOTS;
    if (screenshotDir)
      await page.screenshot({
        animations: 'disabled',
        path: resolve(screenshotDir, `settings-${width}.png`),
      });
    if (width > 720) {
      const sidebar = await page
        .getByRole('complementary', { name: 'Settings sidebar' })
        .boundingBox();
      expect(Math.round(sidebar!.x)).toBe(53);
      expect(Math.round(sidebar!.width)).toBe(280);
      const mark = await page
        .getByRole('link', { name: 'Openlet home' })
        .locator('svg')
        .boundingBox();
      const rail = await page
        .getByRole('navigation', { name: 'Workspace navigation', exact: true })
        .boundingBox();
      const back = await page.getByRole('button', { name: 'Go back', exact: true }).boundingBox();
      expect(Math.abs(mark!.x + mark!.width / 2 - (rail!.x + rail!.width / 2))).toBeLessThan(0.5);
      expect(
        Math.abs(mark!.y + mark!.height / 2 - (back!.y + back!.height / 2)),
      ).toBeLessThanOrEqual(1);
      await page.getByRole('button', { name: 'Appearance', exact: true }).click();
    } else {
      await page.getByRole('button', { name: 'Appearance', exact: true }).click();
    }
    await expect(page.getByRole('heading', { name: 'Appearance', exact: true })).toBeVisible();
    await page.getByRole('combobox', { name: 'Theme', exact: true }).click();
    await page.getByRole('option', { name: 'Light', exact: true }).click();
    await expect(page.locator('html')).not.toHaveClass(/dark/);
    if (screenshotDir)
      await page.screenshot({
        animations: 'disabled',
        path: resolve(screenshotDir, `appearance-${width}.png`),
      });
    await page.getByRole('button', { name: 'Close settings', exact: true }).click();
    if (width <= 720)
      await expect(page.getByRole('button', { name: /Atlas Assistant/ })).toBeVisible();
    else await expect(page.getByRole('heading', { name: 'Atlas', exact: true })).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  });
}

test('original Bloub renderer has distinct shapes, animates on hover and respects reduced motion', async ({
  page,
}) => {
  await page.goto('/app');
  const avatars = page
    .getByRole('complementary', { name: 'Agent sidebar' })
    .locator('[data-avatar=bloub]');
  await expect(avatars).toHaveCount(4);
  const paths = await avatars.evaluateAll((items) =>
    items.map((item) => item.querySelector('g > path')?.getAttribute('d')),
  );
  expect(new Set(paths).size).toBe(4);
  const before = await avatars.first().locator('mask path').nth(1).getAttribute('transform');
  await avatars.first().hover();
  await expect
    .poll(() => avatars.first().locator('mask path').nth(1).getAttribute('transform'))
    .not.toBe(before);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.reload();
  const frozen = await avatars.first().locator('mask path').nth(1).getAttribute('transform');
  await avatars.first().hover();
  await page.waitForTimeout(100);
  expect(await avatars.first().locator('mask path').nth(1).getAttribute('transform')).toBe(frozen);
});
