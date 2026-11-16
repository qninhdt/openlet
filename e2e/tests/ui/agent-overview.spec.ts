import { expect, test } from '@playwright/test';

for (const width of [390, 721, 1344, 1860]) {
  test(`private chat, overview and activity stay separate at ${width}px`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/app');
    if (width <= 720)
      await page.getByRole('button', { name: 'Atlas Assistant', exact: true }).click();
    const chat = page.getByLabel('Atlas private chat', { exact: true });
    await expect(chat.getByRole('textbox', { name: 'Message Atlas', exact: true })).toBeVisible();
    await expect(chat.locator('[data-tool]')).toHaveCount(0);
    await expect(chat).toContainText('Nothing has been published.');
    await page.getByRole('tab', { name: 'Overview', exact: true }).click();
    const overview = page.getByRole('region', { name: 'Agent overview', exact: true });
    await expect(overview.getByRole('heading', { name: 'Atlas', exact: true })).toBeVisible();
    await expect(overview.getByRole('region', { name: 'For you', exact: true })).toContainText(
      'A few decisions for Friday’s launch',
    );
    await expect(overview.getByRole('textbox')).toHaveCount(0);
    await page.getByRole('button', { name: 'Edit agent settings', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Agent settings', exact: true });
    await dialog.getByRole('textbox', { name: 'Name', exact: true }).fill('Atlas Prime');
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(overview.getByRole('heading', { name: 'Atlas', exact: true })).toBeVisible();
    await page.getByRole('tab', { name: 'Activity', exact: true }).click();
    if (width <= 720) await page.getByRole('button', { name: 'Back to chat', exact: true }).click();
    await expect(page.locator('[data-tool]').first()).toBeVisible();
    await expect(
      page.getByRole('textbox', { name: 'Activity messages', exact: true }),
    ).toBeDisabled();
    if (width <= 720)
      await page.getByRole('button', { name: 'Toggle side panel', exact: true }).click();
    await expect(page.getByRole('tab', { name: 'Inbox', exact: true })).toBeVisible();
    const inbox = page.getByRole('list', { name: 'Agent activity', exact: true });
    await expect(inbox.getByRole('listitem')).toHaveCount(6);
    await page.getByRole('button', { name: 'Expand Launch review', exact: true }).click();
    await expect(page.getByRole('img', { name: 'Unread by agent', exact: true })).toBeVisible();
    await expect(
      inbox.locator('[data-activity=message] [data-slot=collapsible-content]').first(),
    ).toHaveCSS('padding-top', '12px');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({
      path: `../.impeccable/review/agent-chat-activity/activity-${width}.png`,
    });
    expect(errors).toEqual([]);
  });
}

test('reply and request drafts coexist, closing keeps pending, chat does not answer a question', async ({
  page,
}) => {
  await page.goto('/app');
  const composer = page.getByRole('textbox', { name: 'Message Atlas', exact: true });
  await composer.fill('Keep working while I decide.');
  const message = page.locator('[aria-label="Atlas private chat"] [data-slot=message]').first();
  await message.hover();
  await message.getByRole('button', { name: 'Reply to message', exact: true }).click();
  await page.getByRole('button', { name: '1 questions · 1 requests', exact: true }).click();
  await page.getByRole('radio', { name: 'Workspace owners', exact: true }).check();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await page.getByRole('checkbox', { name: 'Blog and changelog', exact: true }).check();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  const answer = page.getByRole('textbox', {
    name: 'Anything else I should keep in mind?',
    exact: true,
  });
  await answer.fill('Verify the original quotation.');
  await page.getByRole('button', { name: 'Close requests', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Cancel reply', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(composer).toHaveText('');
  await expect(page.getByRole('button', { name: 'Cancel reply', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '1 questions · 1 requests', exact: true }).click();
  // Reopening restores all values, even though the questionnaire returns to the first step.
  await expect(page.getByRole('radio', { name: 'Workspace owners', exact: true })).toBeChecked();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(
    page.getByRole('checkbox', { name: 'Blog and changelog', exact: true }),
  ).toBeChecked();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(answer).toHaveValue('Verify the original quotation.');
  await page.getByRole('button', { name: 'Send answers', exact: true }).click();
  await expect(
    page.getByRole('button', { name: '0 questions · 1 requests', exact: true }),
  ).toBeVisible();
  await composer.fill('This draft must survive the request.');
  await page.getByRole('button', { name: '0 questions · 1 requests', exact: true }).click();
  await page
    .getByRole('button', { name: 'Read your research documents Pending', exact: true })
    .click();
  await page.getByRole('button', { name: 'Decline', exact: true }).click();
  await expect(composer).toHaveText('This draft must survive the request.');
  await expect(page.getByRole('button', { name: /questions · .*requests/ })).toHaveCount(0);
});

test('activity inbox retains schedule controls and shared file tabs', async ({ page }) => {
  await page.goto('/app');
  await page.getByRole('tab', { name: 'Activity', exact: true }).click();
  await page.getByRole('button', { name: 'Expand Weekly workspace report', exact: true }).click();
  await page.getByRole('button', { name: 'Edit schedule', exact: true }).click();
  await page.getByRole('textbox', { name: 'Title', exact: true }).fill('Monday decisions');
  await page.getByLabel('Monday, at', { exact: true }).fill('10:30');
  await page.getByRole('button', { name: 'Save schedule', exact: true }).click();
  await page.getByRole('button', { name: 'Pause schedule', exact: true }).click();
  await expect(page.getByText('No runs while paused', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Expand Launch review', exact: true }).click();
  await page.getByRole('button', { name: 'Launch plan.md', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Launch plan.md', exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Inbox', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Resume schedule', exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Atlas', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Inbox', exact: true })).toHaveCount(0);
  await expect(page.getByRole('tab', { name: 'Launch plan.md', exact: true })).toBeVisible();
});

for (const own of [false, true]) {
  test(`message actions sit beside the ${own ? 'user' : 'agent'} bubble and share context menu`, async ({
    page,
  }) => {
    await page.goto('/app');
    const chat = page.getByLabel('Atlas private chat', { exact: true });
    const row = chat.locator(`[data-slot=message][data-align=${own ? 'end' : 'start'}]`).last();
    const toolbar = row.locator('[data-slot=message-actions]');
    await page.getByRole('tab', { name: 'Overview', exact: true }).hover();
    await expect(toolbar).toHaveCSS('opacity', '0');
    await row.hover();
    await expect(toolbar).toHaveCSS('opacity', '1');
    const bubble = await row.locator('[data-slot=bubble]').boundingBox();
    const actions = await toolbar.boundingBox();
    expect(
      Math.min(bubble!.y + bubble!.height, actions!.y + actions!.height) -
        Math.max(bubble!.y, actions!.y),
    ).toBeGreaterThan(0);
    if (own) expect(actions!.x + actions!.width).toBeLessThanOrEqual(bubble!.x);
    else expect(actions!.x).toBeGreaterThanOrEqual(bubble!.x + bubble!.width);
    await row.getByRole('button', { name: 'Message actions', exact: true }).click();
    await expect(page.getByRole('menuitem', { name: 'Reply', exact: true })).toBeVisible();
    await expect(page.getByRole('menuitem', { name: 'Copy', exact: true })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('[data-slot=dropdown-menu-content]')).toHaveCount(0);
    await row.click({ button: 'right' });
    await page.getByRole('menuitem', { name: 'Reply', exact: true }).click();
    await expect(chat.getByRole('button', { name: 'Cancel reply', exact: true })).toBeVisible();
    await expect(chat).not.toContainText('UI preview');
    expect(await chat.locator('[data-slot=message]').count()).toBeGreaterThanOrEqual(15);
    await page.screenshot({
      path: `../.impeccable/review/agent-chat-activity/chat-${own ? 'user' : 'agent'}-actions.png`,
    });
  });
}

test('typed inputs and For you are on the appropriate surfaces', async ({ page }) => {
  await page.goto('/app');
  await page.getByRole('tab', { name: 'Overview', exact: true }).click();
  const personal = page.getByRole('region', { name: 'For you', exact: true });
  await expect(personal.getByRole('listitem')).toHaveCount(2);
  await personal
    .getByRole('button', { name: 'A few decisions for Friday’s launch', exact: true })
    .click();
  await expect(page.getByRole('radio', { name: 'Workspace owners', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Close requests', exact: true }).click();
  await page.getByRole('tab', { name: 'Activity', exact: true }).click();
  const activity = page.getByLabel('Atlas conversation', { exact: true });
  for (const kind of ['message', 'notification', 'batch', 'schedule', 'request', 'compaction'])
    await expect(activity.locator(`[data-input=${kind}]`).first()).toBeAttached();
  await expect(
    page
      .getByRole('region', { name: 'Agent inbox', exact: true })
      .getByRole('group', { name: 'Activity scope', exact: true }),
  ).toHaveCount(0);
  await expect(
    activity.getByRole('textbox', { name: 'Activity messages', exact: true }),
  ).toBeDisabled();
  const shell = activity.locator('[data-slot=message-action-shell]').last();
  await shell.hover();
  await shell.getByRole('button', { name: 'Message actions', exact: true }).click();
  await expect(page.getByRole('menuitem', { name: 'Copy', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('[data-slot=dropdown-menu-content]')).toHaveCount(0);
  await shell.click({ button: 'right' });
  await expect(page.getByRole('menuitem', { name: 'Copy', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.screenshot({ path: '../.impeccable/review/agent-chat-activity/activity-inputs.png' });
});

test('input text keeps accessible contrast in every agent color and theme', async ({ page }) => {
  for (const theme of ['light', 'dark'])
    for (const agent of ['atlas', 'scout', 'forge', 'pulse']) {
      await page.addInitScript((value) => localStorage.setItem('openlet-theme', value), theme);
      await page.goto(`/app?agent=${agent}`);
      await page.evaluate((value) => {
        document.documentElement.classList.toggle('dark', value === 'dark');
      }, theme);
      await page.getByRole('tab', { name: 'Activity', exact: true }).click();
      const activity = page.getByLabel(`${agent[0].toUpperCase() + agent.slice(1)} conversation`, {
        exact: true,
      });
      const contrast = await activity.locator('[data-input=batch]').evaluate((el) => {
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = 1;
        const context = canvas.getContext('2d')!;
        const rgb = (color: string) => {
          context.clearRect(0, 0, 1, 1);
          context.fillStyle = color;
          context.fillRect(0, 0, 1, 1);
          return Array.from(context.getImageData(0, 0, 1, 1).data).slice(0, 3);
        };
        const luminance = (c: number[]) =>
          c
            .map((v) => {
              v /= 255;
              return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
            })
            .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
        const bubble = el.closest('[data-slot=bubble-content]')!;
        const background = rgb(getComputedStyle(bubble).backgroundColor);
        return Array.from(el.querySelectorAll('p,span'))
          .filter((node) => node.textContent?.trim())
          .map((node) => {
            let opacity = 1;
            for (
              let parent: Element | null = node;
              parent && parent !== bubble;
              parent = parent.parentElement
            )
              opacity *= Number(getComputedStyle(parent).opacity);
            const color = rgb(getComputedStyle(node).color).map(
              (v, i) => v * opacity + background[i] * (1 - opacity),
            );
            const values = [luminance(color), luminance(background)].sort((a, b) => b - a);
            return (values[0] + 0.05) / (values[1] + 0.05);
          });
      });
      for (const ratio of contrast) expect(ratio, `${agent} ${theme}`).toBeGreaterThanOrEqual(4.5);
      if (agent === 'pulse') {
        await activity.locator('[data-input=batch]').scrollIntoViewIfNeeded();
        await page.screenshot({
          path: `../.impeccable/review/agent-chat-activity/contrast-${theme}.png`,
        });
      }
    }
});
