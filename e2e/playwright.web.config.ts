import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';

const url = process.env.OPENLET_WEB_URL ?? 'http://127.0.0.1:5174';
const port = new URL(url).port || '5174';

export default defineConfig({
  workers: 1,
  timeout: 30_000,
  outputDir: '../.local/e2e/ui',
  reporter: 'list',
  use: { baseURL: url, screenshot: 'only-on-failure' },
  projects: [
    { name: 'public', testDir: './tests/ui' },
    {
      name: 'authenticated',
      testDir: './tests/live-web',
      timeout: 180_000,
      expect: { timeout: 30_000 },
      use: {
        storageState: process.env.OPENLET_WEB_AUTH_STATE,
        viewport: { width: 1440, height: 1000 },
        actionTimeout: 30_000,
      },
    },
  ],
  webServer: {
    command: `pnpm --filter @openlet/web dev --host 127.0.0.1 --port ${port} --strictPort`,
    cwd: fileURLToPath(new URL('..', import.meta.url)),
    url,
    reuseExistingServer: !process.env.CI,
  },
});
