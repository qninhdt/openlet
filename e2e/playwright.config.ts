import { defineConfig } from '@playwright/test';
import { gateway } from './setup/settings.ts';

export default defineConfig({
  testDir: './tests/api',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 90_000 },
  globalSetup: './setup/environment.ts',
  outputDir: '../.local/api-e2e/results',
  reporter: [['list'], ['html', { outputFolder: '../.local/api-e2e/report', open: 'never' }]],
  use: { baseURL: gateway, trace: 'off' },
  // Recovery requires drained storage capabilities before adversarial upload journeys issue URLs.
  projects: [
    { name: 'recovery', testMatch: 'backup-recovery.spec.ts' },
    { name: 'api', testIgnore: 'backup-recovery.spec.ts', dependencies: ['recovery'] },
  ],
});
