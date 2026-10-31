import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: '../tests/external',
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 90_000 },
  reporter: 'list',
  use: { trace: 'off' },
  projects: [{ name: 'api' }],
});
