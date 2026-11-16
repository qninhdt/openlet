import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  testDir: './tests/ui',
  fullyParallel: true,
  timeout: 30_000,
  outputDir: '../.local/e2e/ui',
  reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:5174', screenshot: 'only-on-failure' },
  webServer: {
    command: 'pnpm --filter @openlet/web dev --host 127.0.0.1 --port 5174 --strictPort',
    cwd: fileURLToPath(new URL('..', import.meta.url)),
    url: 'http://127.0.0.1:5174/app',
    reuseExistingServer: !process.env.CI,
  },
});
