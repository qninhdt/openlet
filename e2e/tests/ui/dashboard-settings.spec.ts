import { expect, test } from '@playwright/test';

declare global {
  interface Window {
    messageSounds: number;
  }
}

test('workspace settings follow the dashboard settings frame and have no horizontal overflow', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1851, height: 1000 });
  await page.goto('/app-preview');
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByRole('button', { name: 'Launch workspace settings', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Launch workspace', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Your settings', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Workspaces', exact: true })).toHaveCount(0);
  await page.getByRole('textbox', { name: 'Workspace name', exact: true }).fill('Launch studio');
  await page.getByRole('button', { name: 'Save name', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Workspace name', exact: true })).toHaveValue(
    'Launch studio',
  );
  const sidebar = page.getByRole('complementary', { name: 'Settings sidebar' });
  expect(await sidebar.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await page.screenshot({
    path: '../.impeccable/review/workspace-general-1851.png',
    animations: 'disabled',
    fullPage: true,
  });
  await page.getByRole('button', { name: 'Members', exact: true }).click();
  await expect(page.getByText('You (you)', { exact: true })).toBeVisible();
  await expect(sidebar.getByRole('button', { name: 'Members', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await page.screenshot({
    path: '../.impeccable/review/workspace-members-1851.png',
    animations: 'disabled',
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('textbox', { name: 'Email', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({
    path: '../.impeccable/review/workspace-mobile.png',
    animations: 'disabled',
    fullPage: true,
  });
});

test('rail keeps usage, settings and avatar; the avatar menu opens workspace settings', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1851, height: 1000 });
  await page.goto('/app-preview');
  const rail = page.getByRole('navigation', { name: 'Workspace navigation' });
  const usage = rail.getByRole('button', { name: 'Storage usage', exact: true });
  const settings = rail.getByRole('button', { name: 'Settings', exact: true });
  const avatar = rail.getByRole('button', { name: 'Your account', exact: true });
  const positions = await Promise.all(
    [usage, settings, avatar].map(async (item) => (await item.boundingBox())!.y),
  );
  expect(positions[0]).toBeLessThan(positions[1]);
  expect(positions[1]).toBeLessThan(positions[2]);
  await expect(page.getByRole('button', { name: 'Switch workspace', exact: true })).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: /Switch to .* theme|Questions & requests/ }),
  ).toHaveCount(0);
  await usage.click();
  await expect(page.getByRole('dialog', { name: 'Storage usage' })).toContainText('Available');
  await expect(page.getByRole('dialog', { name: 'Storage usage' })).toHaveCSS('opacity', '1');
  await page
    .getByRole('dialog', { name: 'Storage usage' })
    .evaluate((el) => Promise.all(el.getAnimations().map((a) => a.finished)));
  await page.screenshot({
    path: '../.impeccable/review/storage-popover.png',
    animations: 'disabled',
    fullPage: true,
  });
  await page.keyboard.press('Escape');
  await avatar.click();
  await page.getByRole('menuitem', { name: 'Launch workspace', exact: true }).hover();
  await expect(page.getByRole('menu', { name: 'Launch workspace', exact: true })).toBeVisible();
  await page.screenshot({
    path: '../.impeccable/review/workspace-menu.png',
    animations: 'disabled',
    fullPage: true,
  });
  await page
    .getByRole('menu', { name: 'Launch workspace', exact: true })
    .getByRole('menuitem', { name: 'Workspace settings', exact: true })
    .click();
  await expect(page.getByRole('textbox', { name: 'Workspace name', exact: true })).toBeVisible();
});

test('agent context menu only contains pin and move; extra scheduler and search controls are absent', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/app-preview');
  await expect(page.getByRole('button', { name: /^Actions for (Atlas|Scout|Forge)$/ })).toHaveCount(
    0,
  );
  await expect(page.getByRole('button', { name: 'New schedule', exact: true })).toHaveCount(0);
  await page
    .getByRole('button', { name: 'Scout Researcher', exact: true })
    .click({ button: 'right' });
  await expect(page.getByRole('menuitem', { name: 'Pin agent', exact: true })).toBeVisible();
  await expect(
    page.getByRole('menuitem', {
      name: /Open chat|Agent activity|Agent settings|overview|Move (left|right|earlier|later)/i,
    }),
  ).toHaveCount(0);
  await page.getByRole('menuitem', { name: 'Pin agent', exact: true }).click();
  await page
    .getByRole('button', { name: 'Scout Researcher', exact: true })
    .click({ button: 'right' });
  await expect(page.getByRole('menuitem', { name: 'Unpin agent', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('tab', { name: 'Atlas', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Search messages', exact: true })).toHaveCount(0);
});

test('overview edits identity, avatar, instructions and the combined model picker in place', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1851, height: 1000 });
  await page.goto('/app-preview');
  await page.getByRole('tab', { name: 'Overview', exact: true }).click();
  const overview = page.getByRole('region', { name: 'Agent overview' });
  await expect(overview.getByRole('button', { name: 'Pause', exact: true })).toBeVisible();
  await expect(overview.getByRole('button', { name: /Settings/ })).toHaveCount(0);
  await page.getByRole('textbox', { name: 'Agent name', exact: true }).fill('Atlas Prime');
  await page
    .getByRole('textbox', { name: 'Instructions', exact: true })
    .fill('Keep answers concise.');
  await page.getByRole('button', { name: 'Choose avatar', exact: true }).click();
  await page.getByRole('radio', { name: 'Color vert', exact: true }).click();
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Choose agent model', exact: true }).click();
  await page.getByRole('radio', { name: 'OpenAI', exact: true }).click();
  await page.getByRole('radio', { name: 'openai/gpt-5', exact: true }).click();
  await page.getByRole('combobox', { name: 'Reasoning effort', exact: true }).click();
  await page.getByRole('option', { name: 'high', exact: true }).click();
  await page.screenshot({
    path: '../.impeccable/review/model-picker.png',
    animations: 'disabled',
    fullPage: true,
  });
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Save changes', exact: true })).toHaveCount(0);
  await expect(page.getByRole('textbox', { name: 'Agent name', exact: true })).toHaveValue(
    'Atlas Prime',
  );
  await expect(page.getByRole('textbox', { name: 'Instructions', exact: true })).toHaveValue(
    'Keep answers concise.',
  );
  await page.screenshot({
    path: '../.impeccable/review/user-1851.png',
    animations: 'disabled',
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: '../.impeccable/review/desktop.png',
    animations: 'disabled',
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('textbox', { name: 'Agent name', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({
    path: '../.impeccable/review/mobile.png',
    animations: 'disabled',
    fullPage: true,
  });
});

test('file editing keeps a draft across tabs without version history or extra toolbars', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/app-preview');
  await page.getByRole('tab', { name: 'Atlas', exact: true }).click();
  await page.getByRole('button', { name: 'launch review', exact: true }).last().click();
  const viewer = page.locator('.storage-viewer:visible');
  await viewer.getByRole('tab', { name: 'Code', exact: true }).click();
  const editor = viewer.locator('.cm-content');
  await expect(editor).toBeVisible();
  await expect(viewer.locator('.storage-viewer-head')).toHaveCount(1);
  await expect(viewer.getByRole('button', { name: 'Version history', exact: true })).toHaveCount(0);
  await editor.fill('First saved change');
  await viewer.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(viewer.getByRole('button', { name: 'Save', exact: true })).toBeDisabled();
  await editor.fill('My unsaved draft');
  const fileTab = page
    .getByRole('tablist', { name: 'Agent side panel tabs' })
    .getByRole('tab', { selected: true });
  const name = await fileTab.getAttribute('aria-label');
  await page.getByRole('tab', { name: 'Files', exact: true }).click();
  await page.getByRole('tab', { name: name!, exact: true }).click();
  await expect(editor).toContainText('My unsaved draft');
  await expect(viewer.getByRole('button', { name: 'Save', exact: true })).toBeEnabled();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(viewer.getByRole('button', { name: 'Save', exact: true })).toBeInViewport();
});

test('chat code fences highlight in both themes and file mentions render in Activity', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/app-preview');
  await page.getByRole('tab', { name: 'Atlas', exact: true }).click();
  const composer = page.getByRole('textbox', { name: 'Message Atlas', exact: true });
  await composer.fill(
    'Review `:file[launch notes]{name=team/team-brief}`\n\n```go\npackage main\nfunc main() { println("hello") }\n```',
  );
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  const chat = page.locator('[aria-label="Atlas private chat"]');
  await expect(chat.getByRole('button', { name: 'launch notes', exact: true })).toBeVisible();
  const token = chat.locator('pre code span[style*="--shiki-"]').first();
  await expect(token).toBeVisible();
  await expect(chat.locator('pre[aria-label="go code"]')).toHaveAttribute('data-numbered', 'true');
  const dark = await token.evaluate((element) => getComputedStyle(element).color);
  // The public demo pins a dark wrapper; expose the same component's light CSS too.
  await page.evaluate(() => {
    document.documentElement.classList.remove('dark');
    document.querySelector('div.dark.relative.h-dvh')?.classList.remove('dark');
  });
  await expect
    .poll(() => token.evaluate((element) => getComputedStyle(element).color))
    .not.toBe(dark);
  await page.getByRole('tab', { name: 'Activity', exact: true }).click();
  const input = page.locator('[data-input="message"]').filter({ hasText: 'Review' }).last();
  await expect(input.getByRole('button', { name: 'launch notes', exact: true })).toBeVisible();
  await expect(
    input.getByRole('button', { name: 'Download Launch brief.md', exact: true }),
  ).toBeVisible();
  await expect(page.locator('[aria-label="Agent inbox"]')).not.toContainText(':file[');
  await page.screenshot({ path: '../.local/e2e/message-highlight-files.png' });
});

test('storage content search opens and selects the matching line', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/app-preview');
  await page.getByRole('button', { name: 'Storage', exact: true }).click();
  await page.getByRole('button', { name: 'Search file contents', exact: true }).click();
  const search = page.getByRole('dialog', { name: /^Search / });
  await search
    .getByRole('textbox', { name: 'Search storage contents', exact: true })
    .fill('Thursday');
  await search.getByRole('button', { name: 'Search', exact: true }).click();
  await search
    .getByRole('button', { name: /Thursday review.md/ })
    .first()
    .click();
  await expect(search).not.toBeVisible();
  const viewer = page.locator('.storage-viewer:visible');
  await expect(viewer.locator('.cm-activeLine')).toContainText('Thursday');
});

test('remote storage images load thumbnails and open from a chat file mention', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/app-preview');
  await page.getByRole('tab', { name: 'Atlas', exact: true }).click();
  await page
    .getByRole('textbox', { name: 'Message Atlas', exact: true })
    .fill('Review :file[launch mark]{name=team/team-mark}');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  const chat = page.locator('[aria-label="Atlas private chat"]');
  const thumbnail = chat.getByRole('img', { name: 'Launch mark.png', exact: true });
  await expect(thumbnail).toBeVisible();
  await expect
    .poll(() => thumbnail.evaluate((image) => (image as HTMLImageElement).naturalWidth))
    .toBe(1);
  await chat.getByRole('button', { name: 'launch mark', exact: true }).click();
  const image = page
    .locator('.storage-viewer:visible')
    .getByRole('img', { name: 'Launch mark.png', exact: true });
  await expect(image).toBeVisible();
  await expect
    .poll(() => image.evaluate((image) => (image as HTMLImageElement).naturalWidth))
    .toBe(1);
});

test('message sound waits for delivery and deduplicates a repeated sent message', async ({
  page,
}) => {
  await page.addInitScript(() => {
    const state = window;
    state.messageSounds = 0;
    window.AudioContext = class extends AudioContext {
      createOscillator() {
        const oscillator = super.createOscillator();
        const setFrequency = oscillator.frequency.setValueAtTime.bind(oscillator.frequency);
        oscillator.frequency.setValueAtTime = (value, time) => {
          if (value === 550) state.messageSounds++;
          return setFrequency(value, time);
        };
        return oscillator;
      }
    };
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/app-preview');
  await page.evaluate(() => window.postMessage({ type: 'openlet:preview:pause' }, location.origin));
  expect(await page.evaluate(() => window.messageSounds)).toBe(0);
  await page.getByRole('tab', { name: 'Atlas', exact: true }).click();
  await page
    .getByRole('textbox', { name: 'Message Atlas', exact: true })
    .fill('Sound delivery check');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.messageSounds)).toBe(1);
  await page.evaluate(async () => {
    const key = 'openlet-message-sounds:preview-owner';
    const sent = (JSON.parse(localStorage.getItem(key) ?? '[]') as string[]).find((id) =>
      id.includes(':sent:'),
    )!;
    window.dispatchEvent(
      new CustomEvent('openlet:message-sent', {
        detail: { scope: 'preview-owner:preview', id: sent.split(':sent:')[1] },
      }),
    );
    await navigator.locks.request('openlet-message-sound', () => {});
  });
  expect(await page.evaluate(() => window.messageSounds)).toBe(1);
});

test('read receipt only follows the last user message until the agent replies', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/app-preview');
  await page.getByRole('tab', { name: 'Atlas', exact: true }).click();
  const chat = page.locator('[aria-label="Atlas private chat"]');
  const composer = page.getByRole('textbox', { name: 'Message Atlas', exact: true });
  await composer.fill('First receipt check');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(chat.getByLabel('Read by agent', { exact: true })).toHaveCount(1);
  await composer.fill('Last receipt check');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(chat.getByLabel('Read by agent', { exact: true })).toHaveCount(1);
  const lastMessage = chat.locator('[id^="chat-user-"]').filter({ hasText: 'Last receipt check' });
  await expect(lastMessage).toBeVisible();
  await page.screenshot({
    path: '../.impeccable/review/chat-seen.png',
    animations: 'disabled',
    fullPage: true,
  });
  await expect(chat.getByLabel('Read by agent', { exact: true })).toHaveCount(0);
  await expect(chat.getByLabel('Delivered', { exact: true })).toHaveCount(0);
});

test('For you only shows actionable requests and opens the matching question', async ({ page }) => {
  test.setTimeout(45_000);
  await page.setViewportSize({ width: 1851, height: 1000 });
  await page.goto('/app-preview');
  await page.getByRole('tab', { name: 'Overview', exact: true }).click();
  const requests = page.getByRole('region', { name: 'For you', exact: true });
  await expect(
    requests.getByRole('button', { name: 'Which channels should we prepare?', exact: true }),
  ).toBeVisible({ timeout: 25_000 });
  await page.screenshot({
    path: '../.impeccable/review/for-you-1851.png',
    animations: 'disabled',
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole('region', { name: 'Agent overview', exact: true })
    .evaluate((el) => el.scrollTo(0, 0));
  await page.screenshot({
    path: '../.impeccable/review/for-you-mobile.png',
    animations: 'disabled',
    fullPage: true,
  });
  await requests
    .getByRole('button', { name: 'Which channels should we prepare?', exact: true })
    .click();
  await expect(
    page.getByText('Where should the launch be announced?', { exact: true }),
  ).toBeVisible();
});
