import { expect, test } from '@playwright/test';
import { writeFile } from 'node:fs/promises';

test('composer typing, storage panel operations and chat file drops share real files', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1452, height: 886 });
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/app?view=agents&agent=atlas');
  const input = page.getByRole('textbox', { name: 'Message Atlas', exact: true });
  await input.fill('Check the report');
  await input.press('End');
  await input.press('!');
  await expect(input).toHaveText('Check the report!');
  await page.getByRole('button', { name: 'Toggle side panel', exact: true }).click();
  const panel = page.getByRole('complementary', { name: 'Agent side panel' });
  await expect(page.getByRole('tab', { name: 'Files', exact: true })).toBeVisible();
  await expect(
    page.getByRole('tablist', { name: 'Agent side panel tabs' }).getByTitle('Close Files'),
  ).toHaveCount(0);
  await expect(panel.locator('.storage-browser')).toBeVisible();
  await panel.getByLabel('Upload files', { exact: true }).setInputFiles({
    name: 'Panel.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from('# Shared file\n\nPanel content'),
  });
  const file = panel.getByRole('button', { name: 'Open Panel.md', exact: true });
  await expect(file).toBeVisible();
  await file.click({ button: 'right' });
  await expect(page.getByRole('menuitem', { name: 'Rename', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await panel.getByRole('button', { name: 'New', exact: true }).click();
  await page.getByRole('menuitem', { name: 'New folder', exact: true }).click();
  await page.getByRole('textbox', { name: 'Name', exact: true }).fill('Drafts');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await file.dragTo(input);
  await expect(input).toContainText('Panel.md');
  await expect(input).toContainText('Check the report!');
  await expect(file).toBeVisible();
  await expect(
    page
      .getByRole('region', { name: 'Uploads', exact: true })
      .getByText('Panel.md', { exact: true }),
  ).toHaveCount(1);
  const folder = panel.getByRole('button', { name: 'Open Drafts', exact: true });
  await file.dragTo(folder);
  await folder.click();
  await expect(file).toBeVisible();
  await file.click();
  await expect(page.getByRole('tab', { name: 'Panel.md', exact: true })).toBeVisible();
  await expect(panel.getByRole('heading', { name: 'Shared file', exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Files', exact: true }).click();
  await page.evaluate(() => {
    const flashes: string[] = [];
    (window as unknown as { uploadFlashes: string[] }).uploadFlashes = flashes;
    new MutationObserver((records) => {
      for (const record of records)
        for (const node of record.addedNodes)
          if (node.textContent?.includes('Uploading…')) flashes.push(node.textContent);
    }).observe(document.querySelector('[data-slot=conversation-composer]')!, {
      subtree: true,
      childList: true,
    });
  });
  const drop = await page.evaluateHandle(() => {
    const data = new DataTransfer();
    data.items.add(new File(['Dropped contents'], 'Dropped.txt', { type: 'text/plain' }));
    return data;
  });
  await page
    .getByLabel('Atlas private chat', { exact: true })
    .dispatchEvent('drop', { dataTransfer: drop });
  await expect(input).toContainText('Dropped.txt');
  await expect(page.getByRole('region', { name: 'Uploads', exact: true })).toContainText(
    'Dropped.txt',
  );
  await expect(page.locator('[data-slot=conversation-composer] [role=progressbar]')).toHaveCount(0);
  expect(
    await page.evaluate(() => (window as unknown as { uploadFlashes: string[] }).uploadFlashes),
  ).toEqual([]);
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Dropped.txt', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Dropped.txt', exact: true }).click();
  await expect(panel.getByRole('textbox', { name: 'Edit Dropped.txt', exact: true })).toContainText(
    'Dropped contents',
  );
  await page.screenshot({ path: testInfo.outputPath('conversation-files.png') });
  expect(errors).toEqual([]);
});

test('Box does not expose the agent storage panel', async ({ page }) => {
  await page.goto('/app?view=boxes');
  await expect(page.getByRole('button', { name: 'Toggle side panel', exact: true })).toHaveCount(0);
  await expect(page.getByRole('tab', { name: 'Files', exact: true })).toHaveCount(0);
  await expect(page.getByRole('complementary', { name: 'Agent side panel' })).toHaveCount(0);
});

for (const width of [1452, 390])
  test(`composer keeps typing, selection and Vietnamese text at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 886 });
    await page.goto('/app?view=agents&agent=forge');
    if (width < 721) await page.getByRole('button', { name: 'Forge Builder', exact: true }).click();
    const input = page.getByRole('textbox', { name: 'Message Forge', exact: true });
    await input.click();
    await input.pressSequentially('Please review this report', { delay: 25 });
    const value = () =>
      input.evaluate((element) =>
        element instanceof HTMLTextAreaElement
          ? element.value
          : (element as HTMLElement).innerText.replace(/\n\n/g, '\n'),
      );
    await expect.poll(value).toBe('Please review this report');
    await input.press('Home');
    await input.pressSequentially('Hi, ', { delay: 25 });
    await expect.poll(value).toBe('Hi, Please review this report');
    await input.press('End');
    await page.keyboard.insertText(' — kiểm tra báo cáo tiếng Việt');
    await expect.poll(value).toBe('Hi, Please review this report — kiểm tra báo cáo tiếng Việt');
    await input.press('Shift+Enter');
    await input.pressSequentially('Second line', { delay: 25 });
    await expect
      .poll(value)
      .toBe('Hi, Please review this report — kiểm tra báo cáo tiếng Việt\nSecond line');
    const bounds = await input.boundingBox();
    expect(bounds?.height).toBeGreaterThan(20);
    await page.screenshot({ path: testInfo.outputPath(`composer-${width}.png`) });
  });

test('file mentions find nested files, keep custom labels and remain editable', async ({
  page,
}) => {
  await page.goto('/app?view=agents&agent=forge');
  const input = page.getByRole('textbox', { name: 'Message Forge', exact: true });
  await input.fill('Review @workspace');
  await page.getByRole('option', { name: 'workspace.json', exact: true }).first().click();
  await expect(input).toContainText('workspace.json');
  await expect(input).not.toContainText('@workspace');
  await input.getByRole('button', { name: 'workspace.json', exact: true }).click();
  await page.getByRole('textbox', { name: 'File label', exact: true }).fill('cấu hình dự án');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(input).toContainText('cấu hình dự án');
  await expect(input.getByRole('button', { name: 'cấu hình dự án', exact: true })).toHaveCSS(
    'background-color',
    'rgba(0, 0, 0, 0)',
  );
  await input.press('End');
  await input.pressSequentially(' please', { delay: 10 });
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  const message = page.locator('[data-slot=message][data-align=end]').last();
  await expect(message).toContainText('Review');
  await expect(message).toContainText('please');
  await expect(message.getByRole('button', { name: 'cấu hình dự án', exact: true })).toBeVisible();
  const reference = message.getByRole('button', { name: 'cấu hình dự án', exact: true });
  await expect(reference).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  await expect(reference.locator('span')).toHaveCSS('text-decoration-line', 'underline');
  await expect(page.getByRole('button', { name: 'Forge Builder', exact: true })).toContainText(
    'Review cấu hình dự án please',
  );
  await expect(page.getByRole('button', { name: 'Forge Builder', exact: true })).not.toContainText(
    ':file[',
  );
  await expect(input).toHaveText('');
});

test('fast typing keeps every character and IME Enter does not submit', async ({
  page,
}, testInfo) => {
  await page.goto('/app?view=agents&agent=forge');
  const input = page.getByRole('textbox', { name: 'Message Forge', exact: true });
  const text = 'Review this draft and keep every character. '.repeat(5);
  const started = Date.now();
  await input.pressSequentially(text);
  await expect(input).toHaveText(text.trim());
  const duration = Date.now() - started;
  await testInfo.attach('typing', {
    body: JSON.stringify({ characters: text.length, duration_ms: duration }),
    contentType: 'application/json',
  });
  expect(duration).toBeLessThan(5000);
  await input.dispatchEvent('keydown', {
    key: 'Enter',
    code: 'Enter',
    isComposing: true,
    keyCode: 229,
  });
  await expect(input).toHaveText(text.trim());
  await expect(page.locator('[data-slot=message][data-align=end]').last()).not.toContainText(
    text.trim(),
  );
});

for (const mode of ['Grid', 'Mosaic', 'List'])
  test(`Storage ${mode} drops link selected files into the composer without uploading`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1452, height: 886 });
    await page.goto('/app?view=agents&agent=forge');
    const input = page.getByRole('textbox', { name: 'Message Forge', exact: true });
    await input.fill('Review these');
    await page.getByRole('button', { name: 'Toggle side panel', exact: true }).click();
    const panel = page.getByRole('complementary', { name: 'Agent side panel' });
    await panel.getByLabel('Upload files', { exact: true }).setInputFiles([
      { name: 'First.txt', mimeType: 'text/plain', buffer: Buffer.from('First source') },
      { name: 'Second.txt', mimeType: 'text/plain', buffer: Buffer.from('Second source') },
    ]);
    const first = panel.getByRole('button', { name: 'Open First.txt', exact: true });
    const second = panel.getByRole('button', { name: 'Open Second.txt', exact: true });
    await expect(first).toBeVisible();
    await expect(second).toBeVisible();
    await page.getByRole('button', { name: 'Dismiss uploads', exact: true }).click();
    await panel.getByRole('radio', { name: mode, exact: true }).click();
    await first.click({ modifiers: ['Control'] });
    await second.click({ modifiers: ['Control'] });
    await expect(panel.locator('[data-selected]')).toHaveCount(2);
    await first.dragTo(input);
    await expect(input).toContainText('Review these');
    await expect(input.getByRole('button')).toHaveText(['First.txt', 'Second.txt']);
    await expect(page.getByRole('region', { name: 'Uploads', exact: true })).toHaveCount(0);
    await expect(first).toBeVisible();
    await expect(second).toBeVisible();
    const sources = await panel.locator('[data-node][data-kind=file]').evaluateAll((nodes) =>
      nodes.map((node) => ({
        id: node.getAttribute('data-node'),
        name: node.querySelector('.storage-item-name')?.textContent,
      })),
    );
    await page.getByRole('button', { name: 'Send message', exact: true }).click();
    const message = page.locator('[data-slot=message][data-align=end]').last();
    await expect(message.getByRole('button', { name: 'First.txt', exact: true })).toBeVisible();
    await expect(message.getByRole('button', { name: 'Second.txt', exact: true })).toBeVisible();
    await expect(panel.locator('[data-node][data-kind=file]')).toHaveCount(sources.length);
    for (const source of sources)
      await expect(panel.locator(`[data-node="${source.id}"]`)).toBeVisible();
  });

test('failed conversation uploads retry from the shared panel into their original agent draft', async ({
  page,
}) => {
  await page.goto('/app?view=agents&agent=forge');
  const forge = page.getByRole('textbox', { name: 'Message Forge', exact: true });
  await forge.fill('Forge draft');
  await page.evaluate(() => {
    const put = IDBObjectStore.prototype.put;
    IDBObjectStore.prototype.put = function () {
      IDBObjectStore.prototype.put = put;
      throw new DOMException('Storage is full', 'QuotaExceededError');
    };
  });
  await page.getByLabel('Attach files', { exact: true }).setInputFiles({
    name: 'Retry.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('Saved once'),
  });
  const uploads = page.getByRole('region', { name: 'Uploads', exact: true });
  await expect(uploads).toContainText('Storage is full');
  await expect(uploads.getByRole('button', { name: /^Remove / })).toHaveCount(0);
  await expect(uploads.getByRole('button', { name: /Collapse|Expand/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Send message', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Pulse Signals', exact: true }).click();
  const pulse = page.getByRole('textbox', { name: 'Message Pulse', exact: true });
  await pulse.fill('Pulse draft');
  await uploads.getByRole('button', { name: 'Retry Retry.txt', exact: true }).click();
  await expect(uploads).toContainText('Uploaded');
  await expect(pulse).toHaveText('Pulse draft');
  await page.getByRole('button', { name: 'Forge Builder', exact: true }).click();
  await expect(forge).toContainText('Forge draft');
  await expect(forge.getByRole('button', { name: 'Retry.txt', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Send message', exact: true })).toBeEnabled();
});

test('native OS file drops and Storage drags work with the upload panel open', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 886 });
  await page.goto('/app?view=agents&agent=forge');
  const input = page.getByRole('textbox', { name: 'Message Forge', exact: true });
  await input.fill('Keep this draft');
  const filePath = testInfo.outputPath('Native.txt');
  await writeFile(filePath, 'Native upload bytes');
  const client = await page.context().newCDPSession(page);
  const drop = async () => {
    const box = (await input.boundingBox())!;
    // OS file managers allow copy, not link. A synthetic DOM drop bypasses this browser check.
    for (const type of ['dragEnter', 'dragOver', 'drop'] as const)
      await client.send('Input.dispatchDragEvent', {
        type,
        x: box.x + box.width - 30,
        y: box.y + 12,
        data: { items: [], files: [filePath], dragOperationsMask: 1 },
      });
  };
  await drop();
  await expect(input.getByRole('button', { name: 'Native.txt', exact: true })).toBeVisible();
  await expect(input).toContainText('Keep this draft');
  const uploads = page.getByRole('region', { name: 'Uploads', exact: true });
  await expect(uploads).toContainText('Uploaded');
  await input.press('End');
  await input.press('Shift+Enter');
  await input.pressSequentially('Second line');
  const answer = page.locator('[data-slot=message][data-align=start]').last();
  await answer.hover();
  await answer.getByRole('button', { name: 'Reply to message', exact: true }).click();
  await uploads.getByRole('button', { name: 'Dismiss uploads', exact: true }).click();
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(input).toHaveText('');
  await page.getByRole('button', { name: 'Toggle side panel', exact: true }).click();
  const files = page.getByRole('complementary', { name: 'Agent side panel' });
  const source = files.getByRole('button', { name: 'Open Native.txt', exact: true });
  await source.dragTo(input);
  await expect(input.getByRole('button', { name: 'Native.txt', exact: true })).toBeVisible();
  await expect(source).toBeVisible();
  await expect(uploads).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('native-file-drops.png') });
});
