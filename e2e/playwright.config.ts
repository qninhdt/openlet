import { defineConfig } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { parse } from 'yaml';

const config = parse(readFileSync(new URL('./openlet.test.yaml', import.meta.url), 'utf8'));
export default defineConfig({
  testDir: './tests',
  globalSetup: './fixtures/setup.ts',
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  retries: 0,
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR ?? '../.local/e2e/results/traces',
  reporter: [
    ['list'],
    [
      'junit',
      { outputFile: process.env.PLAYWRIGHT_JUNIT_OUTPUT_FILE ?? '../.local/e2e/results/junit.xml' },
    ],
    [
      'html',
      {
        outputFolder: process.env.PLAYWRIGHT_HTML_OUTPUT_DIR ?? '../.local/e2e/results/html',
        open: 'never',
      },
    ],
  ],
  use: { baseURL: config.services.gateway.public_url },
  projects: [
    { name: 'api', testMatch: 'api/**/*.spec.ts' },
    { name: 'leta', testMatch: 'leta/**/*.spec.ts' },
    {
      name: 'browser',
      testMatch: 'browser/**/*.spec.ts',
      use: { browserName: 'chromium', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
    },
  ],
});
