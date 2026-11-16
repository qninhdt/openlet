import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import type { Page } from '@playwright/test';
async function showActivity(page: Page) {
  await page.getByRole('tab', { name: 'Activity', exact: true }).click();
  if (await page.getByRole('button', { name: 'Back to chat', exact: true }).isVisible())
    await page.getByRole('button', { name: 'Back to chat', exact: true }).click();
}

test('pins are centered, previews truncate, compact sidebar keeps agents usable', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1344, height: 900 });
  await page.goto('/app?agent=forge');
  const pins = page.getByLabel('Pinned agents', { exact: true });
  const bounds = await pins.boundingBox();
  const first = await pins.getByRole('button').first().boundingBox();
  const last = await pins.getByRole('button').last().boundingBox();
  expect(
    Math.abs((first!.x + last!.x + last!.width) / 2 - (bounds!.x + bounds!.width / 2)),
  ).toBeLessThan(1);
  const preview = page.getByText('Updated release.ts. All checks passed.', { exact: true });
  await expect(preview).toHaveCSS('text-overflow', 'ellipsis');
  expect(await preview.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);
  const forge = page.getByRole('button', { name: 'Forge Builder', exact: true });
  await forge.click({ button: 'right' });
  await page.getByRole('menuitem', { name: 'Pin agent', exact: true }).click();
  await expect(pins.getByRole('button', { name: 'Forge Builder', exact: true })).toBeVisible();
  await page.reload();
  await expect(pins.getByRole('button', { name: 'Forge Builder', exact: true })).toBeVisible();
  await page.setViewportSize({ width: 721, height: 900 });
  await expect
    .poll(async () => Math.round((await page.locator('#agent-list').boundingBox())!.width))
    .toBe(88);
  await expect(forge.getByText('Forge', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Search workspace', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Pulse Signals', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Message Pulse', exact: true })).toBeVisible();
  await page.setViewportSize({ width: 1344, height: 900 });
  await expect(
    page
      .getByRole('button', { name: 'Pulse Signals', exact: true })
      .getByText('Pulse', { exact: true }),
  ).toBeVisible();
});

test('file tabs reuse Storage editor, retain drafts, save and download edited bytes', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1344, height: 900 });
  await page.goto('/app?agent=forge');
  await page.getByRole('button', { name: 'Open release.ts', exact: true }).click();
  const editor = page.getByRole('textbox', { name: 'Edit release.ts', exact: true });
  await expect.poll(() => editor.locator('span').count()).toBeGreaterThan(0);
  const content = 'export const title = "Đã chỉnh sửa";';
  await editor.fill(content);
  await expect(page.getByText('Unsaved changes', { exact: true })).toBeVisible();
  const panel = page.getByRole('complementary', { name: 'Agent side panel', exact: true });
  const initial = (await panel.boundingBox())!;
  const list = (await page
    .getByRole('complementary', { name: 'Agent sidebar', exact: true })
    .boundingBox())!;
  await page.getByRole('button', { name: 'Expand side panel', exact: true }).click();
  const expanded = (await panel.boundingBox())!;
  expect(expanded.x).toBeCloseTo(list.x + list.width + 1, 0);
  expect(expanded.width).toBeGreaterThan(initial.width * 2);
  await expect(page.getByRole('tab', { name: 'Forge', exact: true })).toBeHidden();
  await expect(editor).toContainText('Đã chỉnh sửa');
  await page.getByRole('button', { name: 'Restore side panel', exact: true }).click();
  await expect
    .poll(async () => Math.abs((await panel.boundingBox())!.width - initial.width))
    .toBeLessThan(2);
  await expect(editor).toContainText('Đã chỉnh sửa');

  await page.getByRole('tab', { name: 'Overview', exact: true }).click();
  await page.getByRole('tab', { name: 'Forge', exact: true }).click();
  await expect(editor).toContainText('Đã chỉnh sửa');
  await page.getByRole('tab', { name: 'release.ts', exact: true }).press('Delete');
  await expect(page.getByRole('alertdialog')).toContainText('Close without saving?');
  await page.getByRole('button', { name: 'Keep editing', exact: true }).click();
  await expect(editor).toContainText('Đã chỉnh sửa');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(editor).toContainText('Đã chỉnh sửa');
  await editor.press('Control+s');
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeDisabled();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download file', exact: true }).click();
  expect(await readFile((await (await download).path())!, 'utf8')).toBe(content);
  await page.getByRole('button', { name: 'Back to chat', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Message Forge', exact: true })).toBeVisible();
});

test('Markdown source edits render through the shared viewer and protect route navigation', async ({
  page,
}) => {
  await page.goto('/app');
  await page.getByRole('button', { name: 'Open Launch plan.md', exact: true }).first().click();
  await page.getByRole('tab', { name: 'Code', exact: true }).click();
  await page
    .getByRole('textbox', { name: 'Edit Launch plan.md', exact: true })
    .fill('# Unsaved launch\n\n**Review** first.');
  await page.getByRole('tab', { name: 'Preview', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Unsaved launch', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Storage', exact: true }).click();
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Agents', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Unsaved launch', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await page.getByRole('button', { name: 'Storage', exact: true }).click();
  await expect(
    page.getByRole('complementary', { name: 'Storage sidebar', exact: true }),
  ).toBeVisible();
});

test('provider logos follow selected model in header and settings', async ({ page }) => {
  await page.goto('/app');
  const picker = page.getByRole('button', { name: 'Choose agent model', exact: true });
  await expect(picker.locator('svg[data-provider="Anthropic"]')).toBeVisible();
  await picker.click();
  await page.getByRole('radio', { name: 'OpenAI', exact: true }).click();
  await page.getByRole('radio', { name: 'GPT-5', exact: true }).click();
  await page.keyboard.press('Escape');
  await expect(picker.locator('svg[data-provider="OpenAI"]')).toBeVisible();
  await page.getByRole('tab', { name: 'Overview', exact: true }).click();
  await page.getByRole('button', { name: 'Edit agent settings', exact: true }).click();
  await expect(
    page
      .getByRole('form', { name: 'Agent settings', exact: true })
      .locator('[data-provider="OpenAI"]'),
  ).toBeVisible();
  await page.getByRole('textbox', { name: 'Name', exact: true }).fill('Atlas Prime');
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Atlas Prime', exact: true })).toBeVisible();
});

test('assistant-ui composer retains drafts, sends local messages with reply and file', async ({
  page,
}) => {
  await page.goto('/app?agent=forge');
  await page.getByRole('textbox', { name: 'Message Forge', exact: true }).fill('Draft for Forge');
  await page.getByRole('button', { name: 'Pulse Signals', exact: true }).click();
  await page.getByRole('textbox', { name: 'Message Pulse', exact: true }).fill('Pulse draft');
  await page.getByRole('button', { name: 'Forge Builder', exact: true }).click();
  const composer = page.getByRole('textbox', { name: 'Message Forge', exact: true });
  await expect(composer).toHaveText('Draft for Forge');
  const answer = page.locator('[data-slot=message][data-align=start]').last();
  await answer.hover();
  await answer.getByRole('button', { name: 'Reply to message', exact: true }).click();
  await page.getByRole('button', { name: 'Attach file', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Upload file', exact: true }).click();
  await page.getByLabel('Attach files', { exact: true }).setInputFiles({
    name: 'Research notes.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from('# Research notes'),
  });
  await expect(composer).toContainText('Research notes.md');
  await page.getByRole('button', { name: 'Dismiss uploads', exact: true }).click();
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  const message = page.locator('[data-slot=message]').last();
  await expect(message).toContainText('Draft for Forge');
  await expect(message).toContainText('Research notes.md');
  await expect(composer).toHaveText('');
  await expect(page.getByRole('button', { name: 'Cancel reply', exact: true })).toHaveCount(0);
});

test('questions and access decision complete from the composer popup', async ({ page }) => {
  await page.goto('/app');
  await page.getByRole('button', { name: '1 questions · 1 requests', exact: true }).click();
  await page.getByRole('radio', { name: 'Workspace owners', exact: true }).check();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await page.getByRole('checkbox', { name: 'Blog and changelog', exact: true }).check();
  await page.getByRole('checkbox', { name: 'Newsletter', exact: true }).check();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await page
    .getByRole('textbox', { name: 'Anything else I should keep in mind?', exact: true })
    .fill('Wait for approval');
  await page.getByRole('button', { name: 'Send answers', exact: true }).click();
  await page.getByRole('button', { name: '0 questions · 1 requests', exact: true }).click();
  await page
    .getByRole('button', { name: 'Read your research documents Pending', exact: true })
    .click();
  await page.getByRole('button', { name: 'Allow access', exact: true }).click();
  await expect(page.getByRole('button', { name: /questions · .*requests/ })).toHaveCount(0);
});

for (const width of [390, 721, 1344, 1860]) {
  test(`bubbles stay bounded and composer is centered at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 922 });
    await page.goto('/app?agent=forge');
    if (width <= 720)
      await page.getByRole('button', { name: 'Forge Builder', exact: true }).click();
    const sizes = await page.locator('[aria-label="Forge private chat"]').evaluate((el) => {
      const pane = el.getBoundingClientRect();
      const composer = el
        .querySelector('[data-slot=conversation-composer]')!
        .getBoundingClientRect();
      const content = el.querySelector('[data-slot=message-content]')!.getBoundingClientRect();
      const bubbles = Array.from(el.querySelectorAll('[data-slot=bubble]')).map(
        (b) => b.getBoundingClientRect().width,
      );
      return {
        offset: Math.abs(composer.x + composer.width / 2 - (pane.x + pane.width / 2)),
        bubbles,
        max: Math.min(content.width - 60, 720),
      };
    });
    expect(sizes.offset).toBeLessThan(1);
    for (const bubble of sizes.bubbles) expect(bubble).toBeLessThanOrEqual(sizes.max + 1);
    await showActivity(page);
    const toolWidth = await page
      .locator('[data-slot=agent-tool-group]')
      .first()
      .evaluate((el) => el.getBoundingClientRect().width);
    const rowWidth = await page
      .getByLabel('Forge conversation', { exact: true })
      .locator('[data-slot=message-content]')
      .first()
      .evaluate((el) => el.clientWidth);
    expect(Math.abs(toolWidth - rowWidth)).toBeLessThan(1);
    const toolHeader = await page
      .getByRole('button', { name: 'Read ~/release.ts', exact: true })
      .boundingBox();
    expect(toolHeader!.width).toBeLessThan(toolWidth);
    const outputWidth = await page
      .locator('[data-tool-call=forge-success-check] [data-slot=collapsible-content]')
      .evaluate((el) => el.getBoundingClientRect().width);
    await expect(
      page.locator('[data-slot=agent-tool-group] > [data-slot=collapsible-content]').first(),
    ).toHaveCSS('max-height', 'none');
    await expect(
      page.locator('[data-tool-call=forge-success-check] [data-slot=code-block-content]'),
    ).toHaveCSS('max-height', 'none');
    const availableWidth = await page
      .locator('[data-tool-call=forge-success-check]')
      .evaluate((el) => el.clientWidth);
    expect(
      Math.abs(outputWidth - Math.min(availableWidth, Math.max(720, 0.7 * availableWidth), 1200)),
    ).toBeLessThan(1);
    await expect(
      page.getByRole('textbox', { name: 'Activity messages', exact: true }),
    ).toBeDisabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
}

for (const width of [390, 1344]) {
  test(`long demo covers every tool without nested vertical scroll at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const seen = new Set<string>();
    for (const agent of ['atlas', 'forge', 'scout', 'pulse']) {
      await page.goto(`/app?agent=${agent}`);
      if (width <= 720)
        await page.getByRole('button', { name: new RegExp(`^${agent} `, 'i') }).click();
      await showActivity(page);
      await expect(page.locator('[data-tool]').first()).toBeAttached();
      const tools = await page.locator('[data-tool]').evaluateAll((elements) =>
        elements.map((el) => ({
          name: el.getAttribute('data-tool')!,
          right: el.getBoundingClientRect().right,
          scrolls: Array.from(el.querySelectorAll('*')).some((child) => {
            const style = getComputedStyle(child);
            return (
              ['auto', 'scroll'].includes(style.overflowY) &&
              child.scrollHeight > child.clientHeight + 2
            );
          }),
        })),
      );
      for (const tool of tools) {
        seen.add(tool.name);
        expect(tool.right, tool.name).toBeLessThanOrEqual(width + 1);
        expect(tool.scrolls, tool.name).toBe(false);
      }
      expect(await page.locator('[data-slot=message][data-align=start]').count()).toBeGreaterThan(
        3,
      );
      const ids = await page
        .locator('[data-tool-call]')
        .evaluateAll((elements) => elements.map((el) => el.getAttribute('data-tool-call')));
      expect(new Set(ids).size).toBe(ids.length);
    }
    expect([...seen].sort()).toEqual(
      [
        'file_list',
        'file_read',
        'file_write',
        'file_edit',
        'file_semantic_search',
        'execute',
        'inbox_send',
        'inbox_list',
        'inbox_read',
        'inbox_react',
        'schedule_create',
        'schedule_get',
        'schedule_update',
        'schedule_delete',
        'schedule_list',
        'history_search',
        'history_read',
        'workspace_get',
        'workspace_member_list',
        'box_create',
        'box_list',
        'box_get',
        'box_delete',
        'hitl_ask',
        'hitl_request',
        'hitl_get',
        'hitl_list',
        'hitl_cancel',
      ].sort(),
    );
  });
}

test('tool results show failures, diffs, citations, agenda and next runs', async ({ page }) => {
  await page.goto('/app?agent=forge');
  await showActivity(page);
  const failed = page.locator('[data-tool-call=forge-failed-check]');
  await expect(failed).toContainText('ERROR: Budget exceeds limit: 350');
  await expect(failed.locator('[data-slot=code-block]')).toHaveAttribute(
    'data-variant',
    'destructive',
  );
  await expect(failed).not.toContainText('Exit code');
  await expect(failed).not.toContainText('cwd');
  await expect(page.locator('[data-tool-call=forge-success-check]')).toContainText(
    'All checks passed.',
  );
  await expect(page.locator('[data-tool-call=forge-edit] [data-variant=added]')).toHaveCount(1);
  await expect(page.locator('[data-tool-call=forge-edit] [data-variant=removed]')).toHaveCount(1);
  await expect(page.locator('[data-tool=file_list] li')).toHaveCount(7);
  await page
    .getByRole('button', { name: 'Inspect Launch budget.csv', exact: true })
    .first()
    .click();
  await expect(page.getByRole('tab', { name: 'Launch budget.csv', exact: true })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'Newsletter', exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Code', exact: true }).click();
  await expect(
    page.getByRole('textbox', { name: 'Edit Launch budget.csv', exact: true }),
  ).toBeVisible();

  await page.goto('/app?agent=scout');
  await showActivity(page);
  await expect(page.locator('[data-tool-call=scout-search] blockquote')).toHaveCount(2);
  await expect(page.locator('[data-tool-call=scout-no-results]')).toContainText('No evidence');
  await expect(page.getByRole('button', { name: 'Allow editing too', exact: true })).toHaveCount(0);
  await page.goto('/app?agent=pulse');
  await showActivity(page);
  const update = page.locator('[data-tool=schedule_update]');
  await expect(update).toContainText('Every Friday at 08:30 · paused');
  await expect(update).toContainText('Every Friday at 09:00');
  await expect(update).toContainText('Asia/Ho_Chi_Minh');
  await expect(update.locator('ol li')).toHaveCount(3);
  await expect(page.locator('[data-tool=schedule_get]')).toContainText('Paused · no upcoming runs');
  await expect(page.locator('[data-tool=schedule_delete]')).toContainText(
    'Previously delivered messages remain.',
  );
  await expect(page.locator('[data-tool=schedule_create]')).toContainText(
    'Once · Thu, Nov 19 at 16:00',
  );
});

test('agent identity updates shape and bubble color, and file panels contain only files', async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/app');
  const paths = new Set<string>();
  for (const [name, title] of [
    ['Atlas', 'Assistant'],
    ['Scout', 'Research'],
    ['Forge', 'Builder'],
    ['Pulse', 'Signals'],
  ]) {
    await page.getByRole('button', { name: `${name} ${title}`, exact: true }).click();
    const tab = page.getByRole('tablist', { name: 'Agent tabs', exact: true });
    const headerPath = await tab.locator('[data-avatar] g > path').first().getAttribute('d');
    const sidebarPath = await page
      .getByRole('button', { name: `${name} ${title}`, exact: true })
      .locator('[data-avatar] g > path')
      .first()
      .getAttribute('d');
    expect(headerPath).toBe(sidebarPath);
    paths.add(headerPath!);
    const color = await tab
      .locator('[data-avatar] g > path')
      .last()
      .evaluate((el) => getComputedStyle(el).fill);
    await expect(
      page.locator('[data-slot=bubble][data-align=end] > [data-slot=bubble-content]').first(),
    ).toHaveCSS('background-color', color);
  }
  expect(paths.size).toBe(4);
  await page.getByRole('tab', { name: 'Pulse', exact: true }).click();
  await expect(
    page.getByRole('complementary', { name: 'Agent side panel', exact: true }),
  ).toHaveCount(0);
  await page.getByRole('tab', { name: 'Overview', exact: true }).click();
  await page.getByRole('button', { name: 'Edit agent settings', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Agent settings', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: 'Forge Builder', exact: true }).click();
  await page.getByRole('button', { name: 'Open release.ts', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'release.ts', exact: true })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Agent settings', exact: true })).toHaveCount(0);
  await page.getByRole('tab', { name: 'release.ts', exact: true }).press('Delete');
  await expect(page.getByRole('tab', { name: 'Files', exact: true })).toBeVisible();
  await expect(
    page.getByRole('complementary', { name: 'Agent side panel', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Storage', exact: true }).click();
  const sidebar = page.getByRole('complementary', { name: 'Storage sidebar', exact: true });
  for (const name of ['Atlas', 'Forge', 'Scout']) {
    const entry = sidebar.getByRole('button', { name, exact: true });
    await entry.click();
    const crumbPath = await page
      .getByRole('tablist', { name: 'Storage tabs', exact: true })
      .locator('[data-avatar] g > path')
      .first()
      .getAttribute('d');
    expect(crumbPath).toBe(await entry.locator('[data-avatar] g > path').first().getAttribute('d'));
  }
});

test('wide tables and code scroll horizontally inside a bounded mobile message', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/app?agent=forge');
  await page.getByRole('button', { name: 'Forge Builder', exact: true }).click();
  const input = page.getByRole('textbox', { name: 'Message Forge', exact: true });
  await input.fill(
    '| File | Purpose | Owner | Status |\n| --- | --- | --- | --- |\n| Release configuration for the Friday launch | Includes the approved channels and audience | Forge | Waiting for owner approval |\n\n```typescript\nconst description = "This is a deliberately long line that must remain inside the message and scroll horizontally without clipping or expanding the conversation pane.";\n```',
  );
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  const message = page.locator('[data-slot=message]').last();
  const table = message.getByRole('region', { name: 'Scrollable table', exact: true });
  const code = message.locator('[data-slot=code-block-content]');
  for (const region of [table, code]) {
    await expect(region).toHaveCSS('overflow-x', 'auto');
    expect(await region.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);
    await region.evaluate((el) => {
      el.scrollLeft = 200;
    });
    expect(await region.evaluate((el) => el.scrollLeft)).toBeGreaterThan(0);
    expect(await region.evaluate((el) => el.scrollHeight <= el.clientHeight + 2)).toBe(true);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
