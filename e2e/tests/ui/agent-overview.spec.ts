import { expect, test } from '@playwright/test';

test('one activity list mixes messages, questions, requests and schedules without marking agent inbox read', async ({
  page,
}) => {
  await page.goto('/app');
  await page.getByRole('tab', { name: 'Overview', exact: true }).click();
  const overview = page.getByRole('region', { name: 'Agent overview', exact: true });
  const list = page.getByRole('list', { name: 'Agent activity', exact: true });
  await expect(list.getByRole('listitem')).toHaveCount(6);
  for (const kind of ['message', 'question', 'request', 'schedule']) {
    await expect(list.locator(`[data-activity="${kind}"]`).first()).toBeVisible();
  }
  await expect(overview.getByRole('img', { name: 'Unread by agent', exact: true })).toBeVisible();
  await expect(overview.getByRole('img', { name: 'Read by agent', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Expand Launch review', exact: true }).click();
  await expect(overview.getByRole('img', { name: 'Unread by agent', exact: true })).toBeVisible();
  const content = list
    .locator('[data-activity="message"] [data-slot="collapsible-content"]')
    .first();
  await expect(content).toHaveCSS('padding-top', '12px');
  await overview.getByRole('button', { name: 'Launch plan.md', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Launch plan.md', exact: true })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Agent settings', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Forge Builder', exact: true }).click();
  await expect(
    page.getByRole('complementary', { name: 'Agent side panel', exact: true }),
  ).toHaveCount(0);
  await page.getByRole('button', { name: 'Atlas Assistant', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Launch plan.md', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Close side panel', exact: true }).click();
  await page.getByRole('textbox', { name: 'Search agent activity', exact: true }).fill('budget');
  await expect(list.getByRole('listitem')).toHaveCount(2);
  await page.getByRole('textbox', { name: 'Search agent activity', exact: true }).clear();
  await page.getByRole('button', { name: 'Filter activity', exact: true }).click();
  await page.getByRole('menuitemradio', { name: 'Question', exact: true }).click();
  await expect(list.getByRole('listitem')).toHaveCount(2);
  await page.getByRole('button', { name: 'Expand Confirm the launch budget', exact: true }).click();
  await expect(
    overview.getByText('Only Linh can answer this question.', { exact: true }),
  ).toBeVisible();
});

test('questions and requests share decisions with chat and update Needs you without duplicate results', async ({
  page,
}) => {
  await page.goto('/app');
  await page.getByRole('tab', { name: 'Overview', exact: true }).click();
  const overview = page.getByRole('region', { name: 'Agent overview', exact: true });
  await overview.getByRole('button', { name: 'Needs you 2', exact: true }).click();
  await page.getByRole('button', { name: 'Expand Launch decisions', exact: true }).click();
  await overview.getByRole('radio', { name: 'Workspace owners', exact: true }).check();
  await overview.getByRole('button', { name: 'Next', exact: true }).click();
  await overview.getByRole('checkbox', { name: 'Blog and changelog', exact: true }).check();
  await overview.getByRole('checkbox', { name: 'Newsletter', exact: true }).check();
  await overview.getByRole('button', { name: 'Next', exact: true }).click();
  await overview
    .getByRole('textbox', { name: 'Additional launch notes', exact: true })
    .fill('Review the quote before publishing.');
  await overview.getByRole('button', { name: 'Send answers', exact: true }).click();
  await expect(overview.getByRole('listitem')).toHaveCount(1);
  await page.getByRole('button', { name: 'Expand Research source access', exact: true }).click();
  await overview.getByRole('button', { name: 'Allow access', exact: true }).click();
  await expect(overview.getByText('You’re all caught up', { exact: true })).toBeVisible();
  await overview.getByRole('button', { name: 'All', exact: true }).click();
  await expect(overview.getByText('You answered', { exact: true })).toBeVisible();
  await expect(
    overview.getByText('Allowed in this preview · Read only', { exact: true }),
  ).toBeVisible();
  await page.getByRole('tab', { name: 'Atlas', exact: true }).click();
  await expect(page.locator('[data-tool="hitl_ask"]')).toContainText(
    'Review the quote before publishing.',
  );
});

test('schedule edits, pause and search keep their state across agents', async ({ page }) => {
  await page.goto('/app');
  await page.getByRole('tab', { name: 'Overview', exact: true }).click();
  await page.getByRole('button', { name: 'Expand Weekly workspace report', exact: true }).click();
  await page.getByRole('button', { name: 'Edit schedule', exact: true }).click();
  await page.getByRole('textbox', { name: 'Title', exact: true }).fill('Monday decisions');
  await page.getByLabel('Monday, at', { exact: true }).fill('10:30');
  await page.getByRole('button', { name: 'Save schedule', exact: true }).click();
  await expect(page.getByText('Next: Mon, Nov 23 · 10:30', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Pause schedule', exact: true }).click();
  await expect(page.getByText('No runs while paused', { exact: true })).toBeVisible();
  await page
    .getByRole('textbox', { name: 'Search agent activity', exact: true })
    .fill('Monday decisions');
  await expect(page.getByRole('listitem')).toHaveCount(1);
  await page.getByRole('button', { name: 'Forge Builder', exact: true }).click();
  await page.getByRole('button', { name: 'Atlas Assistant', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Overview', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await page.getByRole('button', { name: 'Expand Monday decisions', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Resume schedule', exact: true })).toBeVisible();
  await expect(page.getByText('Every Monday at 10:30', { exact: true })).toBeVisible();
});

for (const width of [390, 721, 1344]) {
  test(`settings modal stages changes and the unified page fits at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto('/app');
    if (width <= 720)
      await page.getByRole('button', { name: 'Atlas Assistant', exact: true }).click();
    await page.getByRole('tab', { name: 'Overview', exact: true }).click();
    const overview = page.getByRole('region', { name: 'Agent overview', exact: true });
    await page.getByRole('button', { name: 'Edit agent settings', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Agent settings', exact: true });
    await dialog.getByRole('textbox', { name: 'Name', exact: true }).fill('Atlas Prime');
    await dialog.getByRole('button', { name: 'Choose agent model', exact: true }).click();
    await page.getByRole('radio', { name: 'OpenAI', exact: true }).click();
    await page.getByRole('radio', { name: 'GPT-5', exact: true }).click();
    await page.keyboard.press('Escape');
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(overview.getByRole('heading', { name: 'Atlas', exact: true })).toBeVisible();
    await expect(overview.locator('[data-provider="Anthropic"]')).toBeVisible();
    await page.getByRole('button', { name: 'Edit agent settings', exact: true }).click();
    await dialog.getByRole('textbox', { name: 'Name', exact: true }).fill('Atlas Prime');
    await dialog.getByRole('button', { name: 'Save changes', exact: true }).click();
    await expect(overview.getByRole('heading', { name: 'Atlas Prime', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Expand Launch decisions', exact: true }).click();
    expect(await overview.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.getByRole('button', { name: 'Agent actions', exact: true }).click();
    await page.getByRole('menuitem', { name: 'Pause agent', exact: true }).click();
    await expect(overview.getByText('Paused', { exact: true })).toBeVisible();
  });
}
