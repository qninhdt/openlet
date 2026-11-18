import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';

const url = new URL(process.env.OPENLET_WEB_URL ?? 'http://127.0.0.1:5174');
if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(url.hostname) || !url.port)
  throw new Error('OPENLET_WEB_URL must be an HTTP loopback URL with a port');

export default defineConfig({
  workers: 1,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  outputDir: '../.local/e2e/ui',
  reporter: 'list',
  use: { baseURL: url.origin, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  projects: [
    { name: 'public', testDir: './tests/browser/public' },
    {
      name: 'workspace',
      testDir: './tests/browser/workspace',
      use: { viewport: { width: 1440, height: 1000 } },
    },
  ],
  webServer: {
    command: `pnpm --filter @openlet/web dev --host 127.0.0.1 --port ${url.port} --strictPort`,
    cwd: fileURLToPath(new URL('..', import.meta.url)),
    url: url.origin,
    env: { VITE_CLERK_PUBLISHABLE_KEY: '', VITE_API_BASE_URL: '' },
  },
});
