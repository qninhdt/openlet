import { expect, test } from '@playwright/test';

test('landing runs the real Openlet app with an isolated, interactive sample workspace', async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors: string[] = [],
    liveRequests: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error' && message.text().includes('same key'))
      errors.push(message.text());
  });
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.origin === new URL(page.url()).origin && url.pathname.startsWith('/v1/'))
      liveRequests.push(url.pathname);
  });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Meet Openlet' })).toBeVisible();
  await page.locator('iframe').scrollIntoViewIfNeeded();
  const preview = page.frameLocator('iframe[title="Openlet app preview"]');
  await expect(
    preview.getByRole('heading', { name: 'Friday’s launch review is ready' }),
  ).toBeVisible();
  await expect(preview.getByRole('button', { name: 'Replay demo' })).toHaveCount(0);
  const inbox = preview.locator('[aria-label="Agent inbox"]');
  await expect(inbox.getByText('Maya Chen', { exact: true })).toHaveCount(1);
  await inbox.getByRole('button', { name: /Maya Chen/ }).click();
  await expect(inbox.getByText('Small change: don’t increase', { exact: false })).toBeVisible();
  await expect(
    inbox.getByText('For Thursday: bring the channel evidence', { exact: false }),
  ).toBeVisible();
  await inbox.getByRole('button', { name: 'All conversations', exact: true }).click();
  await preview.getByRole('button', { name: 'launch review', exact: true }).last().click();
  await expect(
    preview.getByRole('heading', { name: 'Friday launch · review draft', exact: true }),
  ).toBeVisible();
  const table = preview.locator('.storage-markdown [aria-label="Scrollable table"]');
  await expect(table).toBeVisible();
  await expect(table).toHaveCSS('overflow-x', 'auto');
  await preview.getByRole('tab', { name: 'Atlas', exact: true }).click();
  await expect(
    preview
      .locator('[aria-label="Atlas private chat"]')
      .getByText('Small change: don’t increase', { exact: false }),
  ).toHaveCount(0);
  await preview.getByRole('button', { name: 'campaign report', exact: true }).click();
  const report = preview.frameLocator('iframe[title="Campaign review.html"]');
  await expect(
    report.getByRole('heading', { name: 'More traffic. Not more customers.' }),
  ).toBeVisible();
  await expect(report.getByText('$5.01', { exact: true })).toBeVisible();
  await preview.getByRole('button', { name: '1 questions · 0 requests', exact: true }).click();
  await preview.getByRole('checkbox', { name: 'Newsletter', exact: true }).check();
  await preview.getByRole('button', { name: 'Send answers', exact: true }).click();
  await expect(preview.getByText('Confirmed: Newsletter.', { exact: false })).toBeVisible();
  await preview.getByRole('button', { name: 'Scout Researcher', exact: true }).click();
  await expect(preview.getByRole('textbox', { name: 'Message Scout', exact: true })).toBeVisible();
  await expect(preview.getByRole('heading', { name: 'Evidence check' })).toBeVisible();
  await preview
    .getByRole('textbox', { name: 'Message Scout', exact: true })
    .fill('Check the channel data');
  await preview.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(preview.getByText('Check the channel data', { exact: true }).first()).toBeVisible();
  await preview.getByRole('tab', { name: 'Activity', exact: true }).click();
  await expect(preview.locator('[aria-label="Agent activity timeline"]')).toBeVisible();
  await expect(preview.locator('[data-tool="file_read"]').first()).toBeVisible();
  await expect(preview.locator('[data-tool="file_read"] pre').first()).toBeVisible();
  await expect(preview.locator('[data-tool] > button[aria-expanded]')).toHaveCount(0);
  await page.getByRole('button', { name: 'Can several people work with the same agent?' }).click();
  await expect(
    page.getByText('Yes. Each person has a private conversation', { exact: false }),
  ).toBeVisible();
  expect(liveRequests).toEqual([]);
  expect(errors).toEqual([]);
});

test('mobile navigation closes on selection and public pages recover without overflow', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await expect(page.getByRole('navigation', { name: 'Mobile navigation' })).toBeVisible();
  await page
    .getByRole('navigation', { name: 'Mobile navigation' })
    .getByRole('link', { name: 'Questions' })
    .click();
  await expect(page.getByRole('navigation', { name: 'Mobile navigation' })).not.toBeVisible();
  await expect(page.getByRole('heading', { name: 'Questions', exact: true })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.goto('/a-missing-page');
  await expect(page.getByRole('heading', { name: 'This page wandered off' })).toBeVisible();
  await page.getByRole('link', { name: 'Back to home', exact: true }).click();
  await expect(page).toHaveURL('/');
  await page.goto('/join');
  await expect(page.getByRole('heading', { name: 'Invitation missing' })).toBeVisible();
  for (const [path, heading] of [
    ['/privacy', 'Privacy'],
    ['/terms', 'Terms'],
  ]) {
    await page.goto(path);
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: 'Sign in to Openlet' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Continue with Google' })).toBeVisible();
  await expect(page.getByRole('textbox')).toHaveCount(0);
});
