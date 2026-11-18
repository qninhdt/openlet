import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  outputDir: '../../.local/e2e/web-unit',
  reporter: 'list',
});
