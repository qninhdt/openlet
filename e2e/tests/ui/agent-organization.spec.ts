import { expect, test } from '@playwright/test';

for (const theme of ['light', 'dark'])
  test(`reaction picker and anchor ${theme}`, async ({ page }) => {
    await page.setViewportSize({ width: 1344, height: 920 });
    await page.addInitScript((value) => localStorage.setItem('openlet-theme', value), theme);
    await page.goto('/app');
    const chat = page.getByLabel('Atlas private chat', { exact: true });
    const row = chat
      .locator('[data-slot=message-action-shell]')
      .filter({ hasText: 'I’ll prepare the copy and keep publishing on hold.' });
    await row.hover();
    await row.getByRole('button', { name: 'Add reaction', exact: true }).click();
    await expect(page.getByRole('menuitem', { name: 'React 👍', exact: true })).toBeVisible();
    await page.getByRole('menuitem', { name: 'More emoji', exact: true }).click();
    await expect(page.getByRole('menuitem', { name: 'React 🚀', exact: true })).toBeVisible();
    await page.getByRole('menuitem', { name: 'React 👍', exact: true }).click();
    const badge = row.locator('[data-slot=bubble-reactions]');
    await expect(badge).toBeVisible();
    await badge.scrollIntoViewIfNeeded();
    await expect(page.locator('[data-slot=dropdown-menu-content]')).toHaveCount(0);
    await page.screenshot({ path: `../.impeccable/review/agent-reaction-${theme}.png` });
    const geometry = await row.evaluate((el) => {
      const bubble = el.querySelector('[data-slot=bubble]')!;
      const reaction = el.querySelector('[data-slot=bubble-reactions]')!;
      const content = el.querySelector('[data-slot=bubble-content]')!;
      const item = el.closest('[data-slot=message-scroller-item]')!;
      const a = reaction.getBoundingClientRect(),
        b = content.getBoundingClientRect();
      return {
        reaction: { x: a.x, y: a.y, width: a.width, height: a.height, bottom: a.bottom },
        bubble: { x: b.x, y: b.y, right: b.right, bottom: b.bottom },
        wrapperBottom: bubble.getBoundingClientRect().bottom,
        itemBottom: item.getBoundingClientRect().bottom,
        contentVisibility: getComputedStyle(item).contentVisibility,
        style: getComputedStyle(reaction).backgroundColor,
      };
    });
    console.log(theme, geometry);
    expect(geometry.reaction.bottom).toBeGreaterThan(geometry.bubble.bottom);
    expect(geometry.reaction.bottom - geometry.bubble.bottom).toBeLessThanOrEqual(20);
    expect(geometry.reaction.bottom + 3).toBeLessThanOrEqual(geometry.itemBottom);
    expect(geometry.reaction.x + geometry.reaction.width).toBeLessThanOrEqual(
      geometry.bubble.right,
    );
    expect(
      await badge.evaluate((el) => getComputedStyle(el).getPropertyValue('--tw-ring-color')),
    ).toBe(await page.locator('main').evaluate((el) => getComputedStyle(el).backgroundColor));
    const clipped = await chat
      .locator('[data-slot=bubble-reactions]')
      .evaluateAll(
        (badges) =>
          badges.filter(
            (badge) =>
              badge.getBoundingClientRect().bottom + 3 >
              badge.closest('[data-slot=message-scroller-item]')!.getBoundingClientRect().bottom,
          ).length,
      );
    expect(clipped).toBe(0);
    await row.getByRole('button', { name: 'Remove reaction 👍', exact: true }).click();
    await expect(badge).toHaveCount(0);
    await row.click({ button: 'right' });
    await page.getByRole('menuitem', { name: 'React', exact: true }).hover();
    await page.getByRole('menuitem', { name: 'React ❤️', exact: true }).click();
    await expect(row.getByRole('button', { name: 'Remove reaction ❤️' })).toBeVisible();
  });

test('feedback waits silently until a normal chat message arrives', async ({ page }) => {
  await page.goto('/app');
  const chat = page.getByLabel('Atlas private chat', { exact: true });
  const row = chat
    .locator('[data-slot=message-action-shell]')
    .filter({ hasText: 'I’ll prepare the copy and keep publishing on hold.' });
  await row.click({ button: 'right' });
  await page.getByRole('menuitem', { name: 'React', exact: true }).hover();
  await page.getByRole('menuitem', { name: 'React 👍', exact: true }).click();
  await page.getByRole('tab', { name: 'Activity', exact: true }).click();
  const inbox = page.getByRole('region', { name: 'Agent inbox', exact: true });
  await expect(inbox.getByText('Queued silently', { exact: true })).toBeVisible();
  const activity = page.getByLabel('Atlas conversation', { exact: true });
  await expect(
    activity.locator('[data-input=reaction]').filter({ hasText: 'I’ll prepare the copy' }),
  ).toHaveCount(0);
  await page.getByRole('tab', { name: 'Atlas', exact: true }).click();
  await chat
    .getByRole('textbox', { name: 'Message Atlas', exact: true })
    .fill('Please continue with the review.');
  await chat.getByRole('textbox', { name: 'Message Atlas', exact: true }).press('Enter');
  await page.getByRole('tab', { name: 'Activity', exact: true }).click();
  await expect(inbox.getByText('Queued silently', { exact: true })).toHaveCount(0);
  await expect(
    activity.locator('[data-input=reaction]').filter({ hasText: 'I’ll prepare the copy' }),
  ).toBeVisible();
  await expect(
    activity.getByText('Please continue with the review.', { exact: true }),
  ).toBeVisible();
  await activity
    .locator('[data-input=reaction]')
    .filter({ hasText: 'I’ll prepare the copy' })
    .scrollIntoViewIfNeeded();
  await page.screenshot({ path: '../.impeccable/review/agent-reaction-activity.png' });
  const tool = activity.locator('[data-tool-call=atlas-react]');
  await tool.scrollIntoViewIfNeeded();
  await expect(tool.getByText('Reacted 👍', { exact: true })).toBeVisible();
  await page.screenshot({ path: '../.impeccable/review/agent-reaction-tool.png' });
});

test('reaction menu and badge fit on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/app');
  await page.getByRole('button', { name: 'Atlas Assistant', exact: true }).click();
  const chat = page.getByLabel('Atlas private chat', { exact: true });
  const row = chat
    .locator('[data-slot=message-action-shell]')
    .filter({ hasText: 'I’ll prepare the copy and keep publishing on hold.' });
  await row.scrollIntoViewIfNeeded();
  await row.click();
  await row.getByRole('button', { name: 'Add reaction', exact: true }).click({ force: true });
  await page.getByRole('menuitem', { name: 'More emoji', exact: true }).click();
  const menu = page.locator('[data-slot=dropdown-menu-content]');
  const rect = (await menu.boundingBox())!;
  expect(rect.x).toBeGreaterThanOrEqual(0);
  expect(rect.x + rect.width).toBeLessThanOrEqual(390);
  await page.getByRole('menuitem', { name: 'React 🚀', exact: true }).click();
  await expect(menu).toHaveCount(0);
  await expect(row.getByRole('button', { name: 'Remove reaction 🚀', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '../.impeccable/review/agent-reaction-mobile.png' });
});

test('create nested folders inline, move and pin agents without duplicates', async ({ page }) => {
  await page.goto('/app');
  await page.getByRole('button', { name: 'New agent or folder', exact: true }).click();
  await page.getByRole('menuitem', { name: 'New folder', exact: true }).click();
  const input = page.getByRole('textbox', { name: 'New folder name', exact: true });
  await input.fill('Work');
  await input.press('Enter');
  const folder = page.getByRole('button', { name: 'Work', exact: true });
  await expect(folder).toBeVisible();
  await folder.click({ button: 'right' });
  await page.getByRole('menuitem', { name: 'New folder inside', exact: true }).click();
  await input.fill('Research');
  await input.press('Enter');
  await expect(
    page
      .getByRole('region', { name: 'Work / Research', exact: true })
      .getByRole('button', { name: 'Research', exact: true }),
  ).toBeVisible();
  const forge = page.getByRole('button', { name: 'Forge Builder', exact: true });
  await forge.click();
  await page.getByLabel('Forge private chat', { exact: true }).hover();
  await expect(
    page
      .getByRole('region', { name: 'Unread agents', exact: true })
      .getByRole('button', { name: 'Forge Builder', exact: true }),
  ).toHaveCount(0);
  await forge.click({ button: 'right' });
  await page.getByRole('menuitem', { name: 'Move to…', exact: true }).hover();
  await page.getByRole('menuitem', { name: 'Work / Research', exact: true }).click();
  const section = page.getByRole('region', { name: 'Work / Research', exact: true });
  await expect(section.getByRole('button', { name: 'Forge Builder', exact: true })).toBeVisible();
  await forge.click({ button: 'right' });
  await page.getByRole('menuitem', { name: 'Pin agent', exact: true }).click();
  await expect(forge).toHaveCount(1);
  await expect(section.getByRole('button', { name: 'Forge Builder', exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('button', { name: 'Forge Builder', exact: true })).toHaveCount(1);
  await page.getByRole('button', { name: 'Forge Builder', exact: true }).click({ button: 'right' });
  await page.getByRole('menuitem', { name: 'Unpin agent', exact: true }).click();
  await expect(
    page
      .getByRole('region', { name: 'Work / Research', exact: true })
      .getByRole('button', { name: 'Forge Builder', exact: true }),
  ).toBeVisible();
});

test('create agent from the plus menu', async ({ page }) => {
  await page.goto('/app');
  await page.getByRole('button', { name: 'New agent or folder', exact: true }).click();
  await page.getByRole('menuitem', { name: 'New agent', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('textbox', { name: 'Name', exact: true }).fill('Planner');
  await dialog
    .getByRole('textbox', { name: 'Instructions', exact: true })
    .fill('Help plan releases.');
  await dialog.getByRole('button', { name: 'Create agent', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Planner Assistant', exact: true })).toBeVisible();
  await expect(page.getByLabel('Planner private chat', { exact: true })).toBeVisible();
});

test('new folder editor expands a compact sidebar', async ({ page }) => {
  await page.setViewportSize({ width: 721, height: 900 });
  await page.goto('/app');
  await page.getByRole('button', { name: 'New agent or folder', exact: true }).click();
  await page.getByRole('menuitem', { name: 'New folder', exact: true }).click();
  const input = page.getByRole('textbox', { name: 'New folder name', exact: true });
  await expect(input).toBeVisible();
  await input.fill('Projects');
  await input.press('Enter');
  await expect(input).toHaveCount(0);
  await page.setViewportSize({ width: 1344, height: 900 });
  await expect(page.getByRole('button', { name: 'Projects', exact: true })).toBeVisible();
});

for (const width of [1344, 390])
  test(`OpenBot sidebar groups unread chats and restores their folder at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 920 });
    await page.addInitScript(() => {
      localStorage.setItem('openlet-theme', 'dark');
      localStorage.setItem(
        'openlet-agent-sidebar:demo-owner:personal',
        JSON.stringify({
          revision: 0,
          can_create_agent: true,
          layout: {
            pins: ['forge', 'pulse'],
            order: [],
            collapsed: [],
            folders: [
              { id: 'launch', name: 'Launch', parent_id: null },
              { id: 'research', name: 'Research', parent_id: null },
            ],
            assignments: { atlas: 'launch', scout: 'research' },
          },
        }),
      );
    });
    await page.goto('/app');
    const sidebar =
      width === 390
        ? page.locator('#main-content')
        : page.getByRole('complementary', { name: 'Agent sidebar', exact: true });
    const pins = page.getByLabel('Pinned agents', { exact: true });
    const unread = page.getByRole('region', { name: 'Unread agents', exact: true });
    const scout = page.getByRole('button', { name: 'Scout Research', exact: true });
    await expect(unread.getByRole('heading', { name: 'Unread 1', exact: true })).toBeVisible();
    await expect(unread.getByRole('button', { name: 'Scout Research', exact: true })).toBeVisible();
    await expect(pins.locator('[data-slot=agent-unread-badge]')).toHaveCount(2);
    await expect(scout).toHaveCount(1);
    await expect(scout.locator('time')).toBeVisible();
    expect((await scout.boundingBox())!.height).toBe(62);
    const pin = pins.getByRole('button').first();
    expect((await pin.boundingBox())!.width).toBe(72);
    expect((await pin.boundingBox())!.height).toBe(102);
    await expect(pin.locator('[data-avatar]')).toHaveCSS('width', '56px');
    await sidebar.screenshot({ path: `../.impeccable/review/agent-sidebar-${width}.png` });
    await scout.click();
    if (width === 390)
      await page.getByRole('button', { name: 'Back to workspace', exact: true }).click();
    else await page.getByLabel('Scout private chat', { exact: true }).hover();
    const research = page.getByRole('region', { name: 'Research', exact: true });
    await expect(
      research.getByRole('button', { name: 'Scout Research', exact: true }),
    ).toBeVisible();
    await expect(unread).toHaveCount(0);
    await expect(scout.locator('[data-slot=agent-unread-badge]')).toHaveCount(0);
    await page.reload();
    await expect(unread).toHaveCount(0);
    if (width === 390 && !(await sidebar.isVisible()))
      await page.getByRole('button', { name: 'Back to workspace', exact: true }).click();
    await expect(
      research.getByRole('button', { name: 'Scout Research', exact: true }),
    ).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });

test('folder and storage rows keep spacing, with a muted Unassigned heading', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      'openlet-chat-reads:demo-owner:personal',
      JSON.stringify({ scout: 'read', forge: 'read', pulse: 'read' }),
    );
    localStorage.setItem(
      'openlet-agent-sidebar:demo-owner:personal',
      JSON.stringify({
        revision: 0,
        can_create_agent: true,
        layout: {
          pins: [],
          order: [],
          collapsed: [],
          folders: [{ id: 'launch', name: 'Launch', parent_id: null }],
          assignments: { atlas: 'launch', forge: 'launch' },
        },
      }),
    );
  });
  await page.goto('/app');
  const launch = page.getByRole('region', { name: 'Launch', exact: true });
  const atlas = launch.getByRole('button', { name: 'Atlas Assistant', exact: true });
  const forge = launch.getByRole('button', { name: 'Forge Builder', exact: true });
  await expect(forge).toBeVisible();
  expect(
    (await forge.boundingBox())!.y -
      ((await atlas.boundingBox())!.y + (await atlas.boundingBox())!.height),
  ).toBe(4);
  const unassigned = page.getByRole('region', { name: 'Unassigned agents', exact: true });
  const heading = unassigned.getByRole('heading', { name: 'Unassigned', exact: true });
  await expect(heading).toBeVisible();
  const folderColor = await launch
    .getByRole('button', { name: 'Launch', exact: true })
    .evaluate((el) => getComputedStyle(el).color);
  expect(await heading.evaluate((el) => getComputedStyle(el).color)).not.toBe(folderColor);
  await expect(
    unassigned.getByRole('button', { name: 'Pulse Signals', exact: true }),
  ).toBeVisible();
  await page.goto('/app?view=storage');
  const nav = page.getByRole('navigation', { name: 'Storages', exact: true });
  const rows = nav.locator('.storage-root-row');
  await expect(rows.first()).toBeVisible();
  const first = (await rows.nth(0).boundingBox())!,
    second = (await rows.nth(1).boundingBox())!;
  expect(second.y - (first.y + first.height)).toBe(4);
  await nav.screenshot({ path: '../.impeccable/review/storage-sidebar-spacing.png' });
});

for (const width of [390, 1344]) {
  test(`Activity shares one collapse for interleaved thoughts and tools at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 950 });
    await page.goto('/app');
    if (width === 390)
      await page.getByRole('button', { name: 'Atlas Assistant', exact: true }).click();
    await expect(
      page.getByLabel('Atlas private chat', { exact: true }).locator('[data-slot=agent-reasoning]'),
    ).toHaveCount(0);
    await page.getByRole('tab', { name: 'Activity', exact: true }).click();
    if (await page.getByRole('button', { name: 'Back to chat', exact: true }).isVisible())
      await page.getByRole('button', { name: 'Back to chat', exact: true }).click();
    const timeline = page.getByLabel('Atlas conversation', { exact: true });
    const group = timeline.locator('[data-slot=agent-tool-group]').first();
    await expect(group.locator('[data-tool-call=atlas-workspace]')).toHaveCount(1);
    await group.scrollIntoViewIfNeeded();
    await expect(group.locator('[data-slot=agent-reasoning]')).toHaveCount(2);
    await expect(group.locator('[data-tool]')).toHaveCount(3);
    expect(
      await group
        .locator('[data-slot=collapsible-content]')
        .first()
        .locator(':scope > *')
        .evaluateAll((els) =>
          els.map((el) => el.getAttribute('data-tool') ?? el.getAttribute('data-slot')),
        ),
    ).toEqual([
      'agent-reasoning',
      'workspace_get',
      'agent-reasoning',
      'history_search',
      'history_read',
    ]);
    await expect(group.getByText('Reasoning', { exact: true })).toHaveCount(0);
    const answer = timeline.getByText('Last week’s decisions are clear:', { exact: false });
    await expect(answer).toBeVisible();
    expect(await answer.evaluate((el) => !!el.closest('[data-slot=agent-tool-group]'))).toBe(false);
    const trigger = group.getByRole('button', { name: '3 steps', exact: true });
    await trigger.click();
    await expect(group.locator('[data-slot=agent-reasoning]').first()).toBeHidden();
    await expect(group.locator('[data-tool]').first()).toBeHidden();
    await expect(answer).toBeVisible();
    await trigger.focus();
    await page.keyboard.press('Enter');
    await expect(group.locator('[data-slot=agent-reasoning]').first()).toBeVisible();
    for (const tool of await group.locator('[data-tool]').all())
      await tool.locator(':scope > [data-slot=collapsible-trigger]').click();
    await group.screenshot({ path: `../.impeccable/review/agent-reasoning-${width}.png` });
  });
}

test('keyboard opening an unread chat restores its folder without waiting for a pointer', async ({
  page,
}) => {
  await page.goto('/app');
  const forge = page.getByRole('button', { name: 'Forge Builder', exact: true });
  await forge.focus();
  await forge.press('Enter');
  await expect(
    page
      .getByRole('region', { name: 'Launch', exact: true })
      .getByRole('button', { name: 'Forge Builder', exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole('region', { name: 'Unread agents', exact: true })
      .getByRole('button', { name: 'Forge Builder', exact: true }),
  ).toHaveCount(0);
});
