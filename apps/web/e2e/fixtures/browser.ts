import { test as base } from '@playwright/test';

export { expect } from '@playwright/test';
export const workspace = 'preview';
export const agent = 'atlas';

export const test = base.extend({
  page: async ({ page }, provide) => {
    await page.route(
      (url) => url.pathname.startsWith('/v1/'),
      (route) => route.abort(),
    );
    await page.route('**/__browser_fixture/**', (route) => route.fulfill({ status: 501 }));
    await page.route(
      (url) => url.pathname === '/src/main.tsx',
      (route) =>
        route.fulfill({
          contentType: 'text/javascript',
          body: "import '/tests/browser-app.tsx';",
        }),
    );
    await provide(page);
  },
});
