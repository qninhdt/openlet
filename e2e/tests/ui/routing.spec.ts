import { expect, test } from '@playwright/test';

const agent = '/app/personal/agents/atlas';
const storage = '/app/personal/storage/personal%3Apersonal';
const node = (id: string) => encodeURIComponent(`personal:personal:${id}`);

test('agent routes follow history, retain drafts and reconstruct Leti tabs on reload', async ({
  page,
}) => {
  await page.goto(agent);
  const composer = page.getByRole('textbox', { name: 'Message Atlas', exact: true });
  await composer.fill('Keep this draft');
  await page.getByRole('tab', { name: 'Overview', exact: true }).click();
  await expect(page).toHaveURL(`${agent}/overview`);
  await page.getByRole('tab', { name: 'Activity', exact: true }).click();
  await expect(page).toHaveURL(`${agent}/activity`);
  await page.goBack();
  await expect(page.getByLabel('Agent overview', { exact: true })).toBeVisible();
  await page.goForward();
  await expect(page.getByLabel('Atlas conversation', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Atlas', exact: true }).click();
  await expect(composer).toHaveText('Keep this draft');
  await page.getByRole('tab', { name: 'Box', exact: true }).click();
  await expect(page).toHaveURL(`${agent}/box`);
  await page.getByRole('button', { name: 'Open Iris activity', exact: true }).click();
  await expect(page).toHaveURL(`${agent}/letis/atlas-research-iris/activity`);
  await page.reload();
  const tab = page.getByRole('tab', { name: 'Iris · Reporter', exact: true });
  await expect(tab).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByLabel('Iris conversation', { exact: true })).toBeVisible();
  await tab.press('Delete');
  await expect(page).toHaveURL(`${agent}/box`);
  await expect(tab).toHaveCount(0);
});

test('All Box scope survives opening, reloading and closing a Leti', async ({ page }) => {
  await page.goto('/app/personal/boxes');
  await page.getByRole('button', { name: 'Open Iris activity', exact: true }).click();
  await expect(page).toHaveURL(/\/boxes\/atlas\/letis\/atlas-research-iris\/activity\?scope=all$/);
  await page.reload();
  await expect(page.getByRole('button', { name: 'All', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await page.getByRole('tab', { name: 'Iris · Reporter', exact: true }).press('Delete');
  await expect(page).toHaveURL('/app/personal/boxes');
  await expect(page.locator('.box-canvas')).toBeVisible();
});

test('Storage routes retain independent browser folder, deduplicate file tabs and restore storage', async ({
  page,
}) => {
  await page.goto(storage);
  await page.getByRole('button', { name: 'Open Getting started.md', exact: true }).click();
  await expect(page).toHaveURL(`${storage}/files/${node('readme')}`);
  const tabs = page.getByRole('tablist', { name: 'Storage tabs', exact: true });
  await tabs.getByRole('tab', { name: 'Personal', exact: true }).click();
  await page.getByRole('button', { name: 'Open Documents', exact: true }).click();
  await expect(page).toHaveURL(`${storage}/folders/${node('documents')}`);
  await page.getByRole('button', { name: 'Open Project brief.md', exact: true }).click();
  await expect(page).toHaveURL(`${storage}/files/${node('brief')}`);
  await tabs.getByRole('tab', { name: 'Getting started.md', exact: true }).click();
  await tabs.getByRole('tab', { name: 'Personal', exact: true }).click();
  await expect(page).toHaveURL(`${storage}/folders/${node('documents')}`);
  await page.getByRole('button', { name: 'Open Project brief.md', exact: true }).click();
  await expect(tabs.getByRole('tab')).toHaveCount(3);
  await page.getByRole('button', { name: 'Agents', exact: true }).click();
  await page.getByRole('button', { name: 'Storage', exact: true }).click();
  await expect(page).toHaveURL(`${storage}/files/${node('brief')}`);
  await tabs.getByRole('tab', { name: 'Project brief.md', exact: true }).press('Delete');
  await expect(page).toHaveURL(`${storage}/files/${node('readme')}`);
  await tabs.getByRole('tab', { name: 'Getting started.md', exact: true }).press('Delete');
  await expect(page).toHaveURL(`${storage}/folders/${node('documents')}`);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Documents', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Open Project brief.md', exact: true }).click();
  await page.reload();
  await expect(tabs.getByRole('tab', { name: 'Project brief.md', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  );
});

test('dirty drafts survive same-workspace routes and guard leaving even with editor unmounted', async ({
  page,
}) => {
  await page.goto(`${storage}/files/${node('readme')}`);
  await page.getByRole('tab', { name: 'Code', exact: true }).click();
  const editor = page.getByRole('textbox', { name: 'Edit Getting started.md', exact: true });
  await editor.fill('# Unsaved routing draft');
  await page.getByRole('button', { name: 'Agents', exact: true }).click();
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Switch workspace', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Team workspace', exact: true }).click();
  await expect(page.getByRole('alertdialog')).toContainText('Leave without saving?');
  await page.getByRole('button', { name: 'Keep editing', exact: true }).click();
  await expect(page).toHaveURL(agent);
  await page.getByRole('button', { name: 'Storage', exact: true }).click();
  await expect(editor).toContainText('Unsaved routing draft');
  await page.getByRole('button', { name: 'Switch workspace', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Team workspace', exact: true }).click();
  await page.getByRole('button', { name: 'Discard changes', exact: true }).click();
  await expect(page).toHaveURL(/\/app\/team\/storage\//);
});

test('legacy query entries replace history and preserve folder/file targets', async ({ page }) => {
  await page.goto('/login');
  await page.getByRole('link', { name: 'Workspace', exact: true }).click();
  await expect(page).toHaveURL(agent);
  await page.goBack();
  await expect(page).toHaveURL('/login');
  await page.goto(
    `/app?workspace=personal&view=library&storage=personal%3Apersonal&folder=${node('documents')}&file=${node('brief')}`,
  );
  await expect(page).toHaveURL(`${storage}/files/${node('brief')}`);
  await expect(
    page.getByRole('region', { name: 'Preview Project brief.md', exact: true }),
  ).toBeVisible();
  await page.goto('/app?view=schedule&boxAgent=atlas');
  await expect(page).toHaveURL('/app/personal/boxes/atlas');
});

test('unknown canonical resources stay unavailable instead of selecting a default', async ({
  page,
}) => {
  for (const path of [
    '/app/missing/agents/atlas',
    '/app/personal/agents/missing',
    '/app/personal/storage/missing',
    `${storage}/files/missing`,
    `${storage}/folders/missing`,
    `${agent}/letis/missing/activity`,
    '/app/personal/settings/missing',
  ]) {
    await page.goto(path);
    await expect(page.getByRole('alert').first()).toContainText('unavailable');
    await expect(page).toHaveURL(path);
    await expect(page.getByRole('textbox', { name: 'Message Atlas', exact: true })).toHaveCount(0);
  }
});

test('mobile direct Activity and file URLs open the requested content', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${agent}/activity`);
  await page.getByRole('button', { name: 'Back to chat', exact: true }).click();
  await expect(page.getByLabel('Atlas conversation', { exact: true })).toBeVisible();
  await page.goto(`${storage}/files/${node('readme')}`);
  await expect(
    page.getByRole('region', { name: 'Preview Getting started.md', exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: '../.impeccable/review/routing-file-mobile.png' });
});
