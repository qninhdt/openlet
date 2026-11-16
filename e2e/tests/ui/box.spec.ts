import { expect, test } from '@playwright/test';

for (const width of [390, 1344]) {
  test(`Box shows teams and closable Leti activity at ${width}px`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/app');
    if (width === 390)
      await page.getByRole('button', { name: 'Atlas Assistant', exact: true }).click();
    await page.getByRole('tab', { name: 'Box', exact: true }).click();
    const canvas = page.locator('.box-canvas:visible');
    if (width === 390) {
      await expect(canvas.locator('.react-flow__viewport')).toHaveCSS('transform', /matrix\(1,/);
      await page.screenshot({ path: `../.impeccable/review/box-${width}.png` });
      await canvas.getByRole('button', { name: 'Fit boxes', exact: true }).click();
    }
    await expect(
      canvas.getByRole('button', { name: 'Open Iris activity', exact: true }),
    ).toBeVisible();
    await expect(canvas.locator('[data-box-agent=atlas-research-iris]')).toContainText('Reporter');
    await expect(
      canvas.getByRole('button', { name: 'Open Milo activity', exact: true }),
    ).toBeVisible();
    await expect(
      canvas.getByRole('button', { name: 'Open Nova activity', exact: true }),
    ).toBeVisible();
    if (width > 390) await page.screenshot({ path: `../.impeccable/review/box-${width}.png` });
    await canvas.getByRole('button', { name: 'Collapse box Market research', exact: true }).click();
    await expect(
      canvas.getByRole('button', { name: 'Open Iris activity', exact: true }),
    ).toHaveCount(0);
    if (width > 390) {
      await canvas.getByRole('button', { name: 'Zoom in', exact: true }).click();
      const transform = await canvas.locator('.react-flow__viewport').getAttribute('style');
      await page.getByRole('tab', { name: 'Overview', exact: true }).click();
      await expect(page.locator('.box-canvas')).toHaveCount(0);
      await page.getByRole('tab', { name: 'Box', exact: true }).click();
      await expect(
        canvas.getByRole('button', { name: 'Expand box Market research', exact: true }),
      ).toBeVisible();
      await expect(canvas.locator('.react-flow__viewport')).toHaveAttribute('style', transform!);
    }
    await canvas.getByRole('button', { name: 'Expand box Market research', exact: true }).click();
    await canvas.getByRole('button', { name: 'Open Iris activity', exact: true }).click();
    if (width === 390)
      await page.getByRole('button', { name: 'Back to chat', exact: true }).click();
    const tab = page.getByRole('tab', { name: 'Iris · Reporter', exact: true });
    await expect(tab).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByLabel('Iris conversation', { exact: true })).toBeVisible();
    await expect(page.getByRole('textbox', { name: 'Activity is read-only' })).toHaveCount(0);
    if (width > 390) {
      await expect(page.getByLabel('Agent inbox', { exact: true })).toBeVisible();
      await expect(page.getByLabel('Agent inbox', { exact: true })).toContainText('Milo');
    }
    await page.screenshot({ path: `../.impeccable/review/leti-${width}.png` });
    await tab.focus();
    await page.keyboard.press('Delete');
    await expect(tab).toHaveCount(0);
    await expect(page.getByRole('tab', { name: 'Box', exact: true })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await expect(
      canvas.getByRole('button', { name: 'Open Iris activity', exact: true }),
    ).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    expect(errors).toEqual([]);
  });
}

test('workspace Box scopes All and agent and keeps schedules read-only', async ({ page }) => {
  await page.goto('/app?view=boxes');
  await page.getByRole('button', { name: 'Boxes for Atlas', exact: true }).click();
  const canvas = page.locator('.box-canvas:visible');
  await expect(canvas.getByRole('button', { name: 'Open Iris activity', exact: true })).toHaveCount(
    1,
  );
  await canvas.getByRole('button', { name: 'Inspect Morning briefing', exact: true }).click();
  const detail = page.getByLabel('Schedule details', { exact: true });
  await expect(detail).toContainText('Asia/Ho_Chi_Minh');
  await expect(detail.getByRole('textbox')).toHaveCount(0);
  await page.getByRole('button', { name: 'Close schedule details' }).click();
  await page.getByRole('button', { name: 'All', exact: true }).click();
  await expect(page.getByRole('button', { name: 'All', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await expect(canvas.locator('[data-box-agent=atlas]')).toBeAttached();
  await page.screenshot({ path: '../.impeccable/review/box-all.png' });
});

test('settings saves name title and avatar without changing shape on rename', async ({ page }) => {
  await page.goto('/app');
  await page.getByRole('tab', { name: 'Overview', exact: true }).click();
  await page.getByRole('button', { name: 'Edit agent settings', exact: true }).click();
  await page.getByLabel('Title', { exact: true }).fill('Coordinator');
  await page.getByRole('button', { name: 'Choose agent avatar', exact: true }).click();
  await page.getByRole('radio', { name: 'Shape goutte', exact: true }).click();
  await page.getByRole('radio', { name: 'Color bleu', exact: true }).click();
  await page.keyboard.press('Escape');
  await page.getByLabel('Name', { exact: true }).fill('Atlas Prime');
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Atlas Prime', exact: true })).toBeVisible();
  await expect(
    page.getByRole('tab', { name: 'Atlas Prime', exact: true }).locator('[data-avatar]'),
  ).toHaveAttribute('data-shape', 'goutte');
  await expect(page.getByLabel('Agent overview')).toContainText('Coordinator');
});

test('Box keeps cards readable at tablet width in light mode', async ({ page }) => {
  await page.setViewportSize({ width: 721, height: 900 });
  await page.goto('/app');
  await page.getByRole('button', { name: 'Switch to light theme', exact: true }).click();
  await page.getByRole('tab', { name: 'Box', exact: true }).click();
  const canvas = page.locator('.box-canvas:visible');
  await expect(canvas.locator('.react-flow__viewport')).toHaveCSS('transform', /matrix\(1,/);
  await expect(
    canvas.getByRole('button', { name: 'Open Iris activity', exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: '../.impeccable/review/box-721-light.png' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
