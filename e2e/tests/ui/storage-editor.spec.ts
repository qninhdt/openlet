import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';

test('CodeMirror highlights, saves, preserves UTF-8 BOM/CRLF and reloads the actual file', async ({
  page,
}) => {
  await page.goto('/app?view=storage');
  await page.getByLabel('Upload files', { exact: true }).setInputFiles({
    name: 'Config.json',
    mimeType: 'application/json',
    buffer: Buffer.from('\uFEFF{\r\n  "title": "Original"\r\n}\r\n'),
  });
  await page.getByRole('button', { name: 'Open Config.json', exact: true }).click();
  const editor = page.getByRole('textbox', { name: 'Edit Config.json', exact: true });
  await expect(editor).toContainText('Original');
  await expect(page.locator('.cm-editor')).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  await expect.poll(() => editor.locator('span').count()).toBeGreaterThan(0);
  const updated = '{\n  "title": "Đã chỉnh sửa",\n  "count": 42\n}\n';
  await editor.fill(updated);
  await editor.press('Control+s');
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeDisabled();
  await expect(page.getByText('Saved', { exact: true })).toBeVisible();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download file', exact: true }).click();
  const bytes = await readFile((await (await download).path())!);
  expect(bytes.toString('utf8')).toBe('\uFEFF' + updated.replace(/\n/g, '\r\n'));
  await page.reload();
  await expect(editor).toContainText('Đã chỉnh sửa');
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeDisabled();
});

test('Markdown drafts render, survive responsive remounts and protect navigation until discarded', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1452, height: 886 });
  await page.goto('/app?view=storage');
  await page.getByRole('button', { name: 'Open Getting started.md', exact: true }).click();
  await page.getByRole('tab', { name: 'Source', exact: true }).click();
  const editor = page.getByRole('textbox', { name: 'Edit Getting started.md', exact: true });
  await editor.fill('# Draft title\n\n**Uncommitted** text.');
  for (const width of [390, 721, 1452]) {
    await page.setViewportSize({ width, height: 886 });
    await expect(editor).toContainText('Draft title');
    await expect(page.getByText('Unsaved changes', { exact: true })).toBeVisible();
  }
  await page.getByRole('tab', { name: 'Preview', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Draft title', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Close preview', exact: true }).click();
  await expect(page.getByRole('alertdialog')).toContainText('Leave without saving?');
  await page.getByRole('button', { name: 'Keep editing', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Draft title', exact: true })).toBeVisible();
  await page
    .getByRole('navigation', { name: 'Storage path', exact: true })
    .getByRole('button', { name: 'Personal', exact: true })
    .click();
  await page.getByRole('button', { name: 'Discard changes', exact: true }).click();
  await expect(
    page.getByRole('dialog', { name: 'Preview Getting started.md', exact: true }),
  ).toHaveCount(0);
  await page.getByRole('button', { name: 'Open Getting started.md', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'A place for your work', exact: true }),
  ).toBeVisible();
});

test('CSV renders quoted commas, escaped quotes and multiline cells, then saves source edits', async ({
  page,
}) => {
  await page.goto('/app?view=storage');
  await page.getByLabel('Upload files', { exact: true }).setInputFiles({
    name: 'Quoted.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(
      'Name,Note\r\n"Ninh, Q","He said ""hi"""\r\nOther,"Line one\nLine two"\r\n',
    ),
  });
  await page.getByRole('button', { name: 'Open Quoted.csv', exact: true }).click();
  const table = page.getByRole('table', { name: 'CSV preview', exact: true });
  await expect(table.getByRole('cell', { name: 'Ninh, Q', exact: true })).toBeVisible();
  await expect(table.getByRole('cell', { name: 'He said "hi"', exact: true })).toBeVisible();
  await expect(table.getByRole('cell', { name: 'Line one Line two', exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Source', exact: true }).click();
  await page
    .getByRole('textbox', { name: 'Edit Quoted.csv', exact: true })
    .fill('Name,Value\nUpdated,100\n');
  await page.getByRole('tab', { name: 'Preview', exact: true }).click();
  await expect(table.getByRole('cell', { name: '100', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('Saved', { exact: true })).toBeVisible();
  await page.reload();
  await expect(table.getByRole('cell', { name: 'Updated', exact: true })).toBeVisible();
});

test('failed writes retain the draft; truncated and invalid UTF-8 files cannot be overwritten', async ({
  page,
}) => {
  await page.goto('/app?view=storage');
  await page.getByRole('button', { name: 'Open Budget.csv', exact: true }).click();
  await page.getByRole('tab', { name: 'Source', exact: true }).click();
  const editor = page.getByRole('textbox', { name: 'Edit Budget.csv', exact: true });
  await editor.fill('Name,Value\nRetained,1\n');
  await page.evaluate(() => {
    const original = IDBObjectStore.prototype.put;
    IDBObjectStore.prototype.put = function () {
      IDBObjectStore.prototype.put = original;
      throw new DOMException('Storage is full', 'QuotaExceededError');
    };
  });
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Storage is full');
  await expect(editor).toContainText('Retained');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('Saved', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Close preview', exact: true }).click();
  await page.getByLabel('Upload files', { exact: true }).setInputFiles([
    { name: 'Large.txt', mimeType: 'text/plain', buffer: Buffer.from('Line\n'.repeat(210_000)) },
    { name: 'Invalid.txt', mimeType: 'text/plain', buffer: Buffer.from([255, 254, 0, 1]) },
  ]);
  await page.getByRole('button', { name: 'Open Large.txt', exact: true }).click();
  await expect(page.getByText('Read-only · first 1 MB', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0);
  await expect(page.locator('.cm-content')).toHaveAttribute('contenteditable', 'false');
  await page.getByRole('button', { name: 'Close preview', exact: true }).click();
  await page.getByRole('button', { name: 'Open Invalid.txt', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('UTF-8');
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0);
});
