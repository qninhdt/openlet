import { expect, test } from '@playwright/test';
import { fileURLToPath } from 'node:url';

const fixture = fileURLToPath(
  new URL('../../../apps/web/tests/empty-workspace.tsx', import.meta.url),
);

test.beforeEach(async ({ page, baseURL }) => {
  if (!baseURL || !['127.0.0.1', 'localhost'].includes(new URL(baseURL).hostname))
    throw new Error('The empty-workspace fixture must run locally');
  await page.route('**/app{,/**,?*}', async (route) => {
    if (!route.request().isNavigationRequest()) return route.continue();
    await route.fulfill({
      contentType: 'text/html',
      body: `
      <html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>
      <div id="root"></div>
      <script type="module">
        import RefreshRuntime from '/@react-refresh';
        RefreshRuntime.injectIntoGlobalHook(window);
        window.$RefreshReg$ = () => {};
        window.$RefreshSig$ = () => (type) => type;
        window.__vite_plugin_react_preamble_installed__ = true;
      </script>
      <script type="module" src="/@vite/client"></script>
      <script type="module" src="/@fs/${fixture}"></script></body></html>`,
    });
  });
});

test('empty Agent page keeps the shell and opens the existing creation dialog only on request', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/app/preview/agents');
  await expect(page.getByRole('navigation', { name: 'Workspace navigation' })).toBeVisible();
  await expect(page.getByRole('complementary', { name: 'Agent sidebar' })).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Search workspace', exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Agent name', exact: true })).toHaveCount(0);
  await expect(page.getByRole('form', { name: 'New agent', exact: true })).toHaveCount(0);
  await expect(page.getByText('All agents are pinned.', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('tablist', { name: 'Agent tabs' })).toHaveCount(0);
  await expect(page.getByRole('textbox', { name: /^Message / })).toHaveCount(0);
  await page.screenshot({ path: '../.local/e2e/empty-workspace-desktop.png' });
  await page.getByRole('button', { name: 'New agent or folder' }).click();
  await page.getByRole('menuitem', { name: 'New agent', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'New agent', exact: true });
  await expect(dialog.getByRole('textbox', { name: 'Name', exact: true })).toBeVisible();
  await expect(dialog.getByRole('textbox', { name: 'Instructions', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await expect(page.getByRole('complementary', { name: 'Settings sidebar' })).toBeVisible();
  await page.getByRole('button', { name: 'Close settings', exact: true }).click();
  await expect(page).toHaveURL('/app/preview/agents');
  await page.getByRole('button', { name: 'Storage', exact: true }).click();
  await expect(page.getByRole('complementary', { name: 'Storage sidebar' })).toBeVisible();
  await expect.poll(() => new URL(page.url()).search).toBe('');
  await page.getByRole('button', { name: 'Box', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Box', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Agents', exact: true }).click();
  await expect(page).toHaveURL('/app/preview/agents');
  const calls = await page.evaluate(
    () =>
      (
        window as unknown as {
          emptyWorkspaceCalls: { path: string; method: string }[];
        }
      ).emptyWorkspaceCalls,
  );
  expect(
    calls.filter((c) => c.method !== 'GET' || /\/letas\/(?!sidebar|models|box-view)/.test(c.path)),
  ).toEqual([]);
  expect(errors).toEqual([]);
});

for (const entry of [
  '/app',
  '/app?workspace=preview&view=agents&agent=&section=general&storage=&folder=&file=&boxAgent=&mainTab=agent',
]) {
  test(`legacy entry clears default parameters: ${entry}`, async ({ page }) => {
    await page.goto(entry);
    await expect(page).toHaveURL('/app/preview/agents');
    await expect(page.getByRole('complementary', { name: 'Agent sidebar' })).toBeVisible();
  });
}

test('mobile empty workspace keeps navigation and has no horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/app/preview/agents');
  await expect(page.getByRole('button', { name: 'New agent or folder' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Mobile pane navigation' })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Agent name', exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '../.local/e2e/empty-workspace-mobile.png' });
});

test('an explicit missing agent still shows unavailable', async ({ page }) => {
  await page.goto('/app/preview/agents/missing');
  await expect(
    page.getByText('This workspace or agent does not exist, or you no longer have access.'),
  ).toBeVisible();
});
