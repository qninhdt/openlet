import { expect, test } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';

const contents = (page: import('@playwright/test').Page) =>
  page.getByLabel('Folder contents', { exact: true });

test('storage sidebar contains only roots, nested folders and breadcrumb follow history', async ({
  page,
}) => {
  await page.goto('/app?view=storage');
  const sidebar = page.getByRole('complementary', { name: 'Storage sidebar' });
  await expect(
    sidebar.getByRole('navigation', { name: 'Storages', exact: true }).getByRole('button'),
  ).toHaveCount(6);
  await expect(sidebar.getByText('Documents', { exact: true })).toHaveCount(0);
  await expect(sidebar.getByRole('button', { name: /Expand|Collapse/ })).toHaveCount(0);
  await contents(page).getByRole('button', { name: 'Open Documents', exact: true }).click();
  await contents(page).getByRole('button', { name: 'Open Projects', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
  await expect(
    contents(page).getByRole('button', { name: 'Open workspace.json', exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Go back', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Documents', exact: true })).toBeVisible();
  await sidebar.getByRole('button', { name: 'Atlas', exact: true }).click();
  await expect(
    contents(page).getByRole('button', { name: 'Open Notes.md', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Switch workspace', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Team workspace' }).click();
  await expect(sidebar.getByRole('button', { name: 'Atlas', exact: true })).toHaveCount(0);
  await expect(sidebar.getByRole('button', { name: 'Sage', exact: true })).toBeVisible();
});

test('folder create, rename validation, copy conflict, trash subtree and restore persist', async ({
  page,
}) => {
  await page.goto('/app?view=storage');
  await page.getByRole('button', { name: 'New', exact: true }).click();
  await page.getByRole('menuitem', { name: 'New folder', exact: true }).click();
  await page.getByRole('textbox', { name: 'Name', exact: true }).fill('Drafts');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(
    contents(page).getByRole('button', { name: 'Open Drafts', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Actions for Drafts', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Rename', exact: true }).click();
  await page.getByRole('textbox', { name: 'Name', exact: true }).fill('Documents');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('already exists');
  await page.getByRole('textbox', { name: 'Name', exact: true }).fill('Final drafts');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await page.getByRole('button', { name: 'Actions for Documents', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Copy to…', exact: true }).click();
  await page.getByRole('button', { name: 'Copy here', exact: true }).click();
  await page.getByRole('button', { name: 'Keep both', exact: true }).click();
  await expect(
    contents(page).getByRole('button', { name: 'Open Documents (2)', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Actions for Documents (2)', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Move to Trash', exact: true }).click();
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Move to Trash', exact: true })
    .click();
  await page.getByRole('button', { name: /^Trash/ }).click();
  await page.getByRole('button', { name: 'Actions for Documents (2)', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Restore', exact: true }).click();
  await page
    .getByRole('navigation', { name: 'Storages', exact: true })
    .getByRole('button', { name: 'Personal', exact: true })
    .click();
  await page.reload();
  await contents(page).getByRole('button', { name: 'Open Documents (2)', exact: true }).click();
  await expect(
    contents(page).getByRole('button', { name: 'Open Projects', exact: true }),
  ).toBeVisible();
});

test('file upload, actual download, markdown viewer and selection survive view changes', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/app?view=storage');
  await page.getByLabel('Upload files', { exact: true }).setInputFiles({
    name: 'Review.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from('# Review draft\n\n**Ready** for feedback.'),
  });
  await expect(
    contents(page).getByRole('button', { name: 'Open Review.md', exact: true }),
  ).toBeVisible();
  await contents(page).getByRole('button', { name: 'Open Review.md', exact: true }).click();
  const viewer = page.getByRole('dialog', { name: 'Preview Review.md', exact: true });
  await expect(viewer.getByRole('heading', { name: 'Review draft', exact: true })).toBeVisible();
  await viewer.getByRole('tab', { name: 'Source', exact: true }).click();
  await expect(viewer.locator('.cm-content')).toContainText('# Review draft');
  const download = page.waitForEvent('download');
  await viewer.getByRole('button', { name: 'Download file', exact: true }).click();
  expect((await download).suggestedFilename()).toBe('Review.md');
  await page.keyboard.press('Escape');
  await expect(viewer).toHaveCount(0);
  await contents(page)
    .getByRole('button', { name: 'Open Review.md', exact: true })
    .click({ modifiers: ['Control'] });
  await page.getByRole('radio', { name: 'List', exact: true }).click();
  await expect(page.getByRole('toolbar', { name: 'Selected files', exact: true })).toContainText(
    '1 selected',
  );
  await page.getByRole('radio', { name: 'Mosaic', exact: true }).click();
  await expect(
    contents(page).getByRole('button', { name: 'Open Review.md', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true');
  expect(
    await contents(page)
      .locator('[data-selected]')
      .first()
      .evaluate((element) => {
        const style = getComputedStyle(element);
        return style.backgroundColor === style.getPropertyValue('--accent').trim();
      }),
  ).toBe(true);
  await page.reload();
  await expect(page.getByRole('radio', { name: 'Mosaic', exact: true })).toHaveAttribute(
    'data-state',
    'on',
  );
  await expect(
    contents(page).getByRole('button', { name: 'Open Review.md', exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test('right click and drag move files, cross-storage drag requires destination confirmation', async ({
  page,
}) => {
  await page.goto('/app?view=storage');
  const file = contents(page)
    .locator('[data-node]')
    .filter({ has: page.getByRole('button', { name: 'Open Budget.csv', exact: true }) });
  const folder = contents(page)
    .locator('[data-node]')
    .filter({ has: page.getByRole('button', { name: 'Open Documents', exact: true }) });
  await file.click({ button: 'right' });
  await expect(page.getByRole('menuitem', { name: 'Move to…', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await file.dragTo(folder);
  await expect(
    contents(page).getByRole('button', { name: 'Open Budget.csv', exact: true }),
  ).toHaveCount(0);
  await contents(page).getByRole('button', { name: 'Open Documents', exact: true }).click();
  await expect(
    contents(page).getByRole('button', { name: 'Open Budget.csv', exact: true }),
  ).toBeVisible();
  const moved = contents(page)
    .locator('[data-node]')
    .filter({ has: page.getByRole('button', { name: 'Open Budget.csv', exact: true }) });
  await moved.dragTo(
    page
      .getByRole('navigation', { name: 'Storages', exact: true })
      .getByRole('button', { name: 'Atlas', exact: true }),
  );
  await expect(page.getByRole('dialog')).toContainText('permissions will apply');
  await page.getByRole('button', { name: 'Move here', exact: true }).click();
  await page
    .getByRole('navigation', { name: 'Storages', exact: true })
    .getByRole('button', { name: 'Atlas', exact: true })
    .click();
  await expect(
    contents(page).getByRole('button', { name: 'Open Budget.csv', exact: true }),
  ).toBeVisible();
});

for (const width of [390, 721, 1440]) {
  test(`storage views and image viewer fit ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/app?view=storage&storage=personal%3Ateam');
    await expect(
      contents(page).getByRole('button', { name: 'Open Studio.jpg', exact: true }),
    ).toBeVisible();
    const dir = process.env.OPENLET_STORAGE_SCREENSHOTS;
    async function capture(name: string) {
      if (dir) {
        await mkdir(dir, { recursive: true });
        await page.screenshot({
          path: resolve(dir, `${name}-${width}.png`),
          animations: 'disabled',
        });
      }
    }
    await capture('storage-grid');
    await page.getByRole('radio', { name: 'Mosaic', exact: true }).click();
    await page
      .locator('.storage-item-preview img')
      .first()
      .evaluate((image: HTMLImageElement) => image.decode());
    await capture('storage-mosaic');
    await contents(page).getByRole('button', { name: 'Open Studio.jpg', exact: true }).click();
    await expect(
      page
        .getByRole('dialog', { name: 'Preview Studio.jpg', exact: true })
        .getByRole('img', { name: 'Studio.jpg', exact: true }),
    ).toBeVisible();
    await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
    await expect(page.getByText('125%', { exact: true })).toBeVisible();
    await capture('storage-viewer');
    await page.getByRole('button', { name: 'Previous image', exact: true }).click();
    await expect(page.getByRole('dialog', { name: /Preview/ })).not.toHaveAttribute(
      'aria-label',
      'Preview Studio.jpg',
    );
    await page.getByRole('button', { name: 'Close preview', exact: true }).click();
    await page.getByRole('radio', { name: 'List', exact: true }).click();
    if (width === 721) {
      await expect(contents(page).locator('.storage-item-date').first()).toBeHidden();
      const nameWidth = await contents(page)
        .locator('.storage-item-name')
        .first()
        .evaluate((element) => element.getBoundingClientRect().width);
      expect(nameWidth).toBeGreaterThan(140);
    }
    await capture('storage-list');
    if (width !== 721) {
      await page.getByRole('button', { name: 'Actions for Budget.csv', exact: true }).click();
      await capture('storage-menu');
      await page.keyboard.press('Escape');
      await page.getByRole('button', { name: 'Select files', exact: true }).click();
      await contents(page).getByRole('button', { name: 'Open Budget.csv', exact: true }).click();
      await capture('storage-selection');
      await page.getByRole('button', { name: 'Clear selection', exact: true }).click();
      await page.getByRole('button', { name: 'New', exact: true }).click();
      await page.getByRole('menuitem', { name: 'New folder', exact: true }).click();
      await capture('storage-dialog');
      await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    }

    if (width === 390) {
      await page.getByRole('button', { name: 'Workspace', exact: true }).click();
      await expect(page.getByRole('navigation', { name: 'Storages', exact: true })).toBeVisible();
      await capture('storage-sidebar');
      await page
        .getByRole('navigation', { name: 'Storages', exact: true })
        .getByRole('button', { name: 'Atlas', exact: true })
        .click();
      await expect(
        contents(page).getByRole('button', { name: 'Open Notes.md', exact: true }),
      ).toBeVisible();
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
}

test('XLSX sheet switching, sandboxed HTML and unsupported file fallback', async ({ page }) => {
  await page.goto('/app?view=storage');
  await page
    .getByLabel('Upload files', { exact: true })
    .setInputFiles(resolve(import.meta.dirname, '../../fixtures/storage-preview.xlsx'));
  await contents(page)
    .getByRole('button', { name: 'Open storage-preview.xlsx', exact: true })
    .click();
  const workbook = page.getByRole('dialog', { name: 'Preview storage-preview.xlsx', exact: true });
  await expect(workbook.getByRole('cell', { name: '1200', exact: true })).toBeVisible();
  await workbook.getByRole('tab', { name: 'Notes', exact: true }).click();
  await expect(workbook.getByRole('cell', { name: 'Approved', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Close preview', exact: true }).click();
  await page.getByLabel('Upload files', { exact: true }).setInputFiles({
    name: 'Preview.html',
    mimeType: 'text/html',
    buffer: Buffer.from(
      '<h1>Document preview</h1><script>parent.document.body.dataset.unsafe="yes"</script>',
    ),
  });
  await contents(page).getByRole('button', { name: 'Open Preview.html', exact: true }).click();
  await expect(
    page
      .frameLocator('iframe[title="Preview.html"]')
      .getByRole('heading', { name: 'Document preview' }),
  ).toBeVisible();
  expect(await page.locator('body').getAttribute('data-unsafe')).toBeNull();
  await page.getByRole('button', { name: 'Close preview', exact: true }).click();
  await page.getByLabel('Upload files', { exact: true }).setInputFiles({
    name: 'Design.fig',
    mimeType: 'application/octet-stream',
    buffer: Buffer.from('example'),
  });
  await contents(page).getByRole('button', { name: 'Open Design.fig', exact: true }).click();
  await expect(
    page.getByRole('dialog').getByText('No preview available', { exact: true }),
  ).toBeVisible();
});

test('OS file drop, keyboard range selection, marquee and background paste', async ({ page }) => {
  await page.goto('/app?view=storage');
  await expect(
    contents(page).getByRole('button', { name: 'Open Documents', exact: true }),
  ).toBeVisible();
  const data = await page.evaluateHandle(() => {
    const data = new DataTransfer();
    data.items.add(new File(['A dropped file'], 'Dropped.txt', { type: 'text/plain' }));
    return data;
  });
  await contents(page).dispatchEvent('drop', { dataTransfer: data });
  await expect(
    contents(page).getByRole('button', { name: 'Open Dropped.txt', exact: true }),
  ).toBeVisible();
  await contents(page)
    .getByRole('button', { name: 'Open Budget.csv', exact: true })
    .click({ modifiers: ['Control'] });
  await contents(page)
    .getByRole('button', { name: 'Open Getting started.md', exact: true })
    .click({ modifiers: ['Shift'] });
  await expect(page.getByRole('toolbar', { name: 'Selected files', exact: true })).toContainText(
    '3 selected',
  );
  await page.keyboard.press('Escape');
  await contents(page).click({ position: { x: 10, y: 400 } });
  await page.keyboard.press('Control+a');
  await expect(page.getByRole('toolbar', { name: 'Selected files', exact: true })).toContainText(
    '5 selected',
  );
  await page.keyboard.press('Escape');
  const bounds = (await contents(page).boundingBox())!;
  await page.mouse.move(bounds.x + 1, bounds.y + 2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width - 8, bounds.y + 280, { steps: 12 });
  await page.mouse.up();
  await expect(page.getByRole('toolbar', { name: 'Selected files', exact: true })).toBeVisible();
});

for (const width of [390, 721, 1452]) {
  test(`storage breadcrumb, folder rows and menu widths at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 932 });
    await page.goto('/app?view=storage');
    const path = page.getByRole('navigation', { name: 'Storage path', exact: true });
    const root = path.getByRole('button', { name: 'Personal', exact: true });
    await expect(root.locator('svg')).toHaveCount(1);
    const rootBounds = (await root.boundingBox())!;
    const documents = contents(page)
      .locator('[data-node]')
      .filter({ has: page.getByRole('button', { name: 'Open Documents', exact: true }) });
    await expect(documents.locator('.storage-folder-contents')).toHaveCount(0);
    await expect(documents.locator('.storage-item-size')).toBeHidden();
    await expect(contents(page).getByRole('checkbox')).toHaveCount(0);
    await documents.hover();
    const mark = (await documents.locator('.storage-file-icon').boundingBox())!;
    expect(mark.x - (await documents.boundingBox())!.x).toBeLessThanOrEqual(16);
    expect((await documents.boundingBox())!.height).toBe(54);
    const before = await documents.boundingBox();
    await page.mouse.move(0, 0);
    expect(await documents.boundingBox()).toEqual(before);
    if (width > 720)
      await expect(
        page.getByRole('navigation', { name: 'Storages', exact: true }).getByRole('separator'),
      ).toHaveCount(1);
    async function validMenu() {
      const menu = page.getByRole('menu');
      await expect(menu).toBeVisible();
      const bounds = (await menu.boundingBox())!;
      await expect
        .poll(async () => Math.round((await menu.boundingBox())!.width))
        .toBeGreaterThanOrEqual(192);
      expect(bounds.x).toBeGreaterThanOrEqual(0);
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
      await expect(menu).toHaveCSS('padding', '6px');
      for (const item of await menu.getByRole('menuitem').all()) {
        const size = (await item.boundingBox())!;
        expect(size.height).toBeLessThanOrEqual(32);
      }
    }
    await page.getByRole('button', { name: 'New', exact: true }).click();
    await validMenu();
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: 'Actions for Documents', exact: true }).click();
    await validMenu();
    await expect(page.getByRole('menu').getByRole('separator')).toHaveCount(1);
    await page.getByRole('menuitem', { name: 'Open', exact: true }).hover();
    const dir = process.env.OPENLET_STORAGE_SCREENSHOTS;
    if (dir)
      await page.screenshot({
        path: resolve(dir, `storage-folder-menu-${width}.png`),
        animations: 'disabled',
      });
    await page.keyboard.press('Escape');
    await documents.click({ button: 'right' });
    await validMenu();
    await page.keyboard.press('Escape');
    await documents.getByRole('button', { name: 'Open Documents', exact: true }).click();
    const documentsLabel = path
      .getByRole('button', { name: 'Documents', exact: true })
      .locator('span');
    const documentsPosition = await documentsLabel.boundingBox();
    await contents(page).getByRole('button', { name: 'Open Projects', exact: true }).click();
    expect(await documentsLabel.boundingBox()).toEqual(documentsPosition);
    const projectsLabel = path
      .getByRole('button', { name: 'Projects', exact: true })
      .locator('span');
    const projectsPosition = await projectsLabel.boundingBox();
    await expect(root).toBeVisible();
    expect((await root.boundingBox())!.x).toBeCloseTo(rootBounds.x, 0);
    await contents(page).getByRole('button', { name: 'Open workspace.json', exact: true }).click();
    await expect(
      page
        .getByRole('dialog', { name: 'Preview workspace.json', exact: true })
        .locator('.cm-content'),
    ).toContainText('OpenLet');
    await expect(path.getByRole('heading', { name: 'workspace.json', exact: true })).toBeVisible();
    await expect(root.locator('svg')).toHaveCount(1);
    expect(await documentsLabel.boundingBox()).toEqual(documentsPosition);
    expect(await projectsLabel.boundingBox()).toEqual(projectsPosition);
    await expect(
      page.getByRole('dialog', { name: 'Preview workspace.json', exact: true }),
    ).toBeVisible();
    const headerActions = await page.locator('.page-header-actions').boundingBox();
    expect(headerActions!.x + headerActions!.width).toBeLessThanOrEqual(width);
    const main = await page.getByRole('main').boundingBox();
    expect(main!.x + main!.width).toBeLessThanOrEqual(width);
    if (width > 720)
      expect(
        (await page
          .getByRole('navigation', { name: 'Workspace navigation', exact: true })
          .boundingBox())!.x,
      ).toBe(0);

    await expect(path.getByRole('heading', { name: 'workspace.json', exact: true })).toBeVisible();
    if (dir)
      await page.screenshot({
        path: resolve(dir, `storage-file-path-${width}.png`),
        animations: 'disabled',
      });
    await root.click();
    await expect(
      page.getByRole('dialog', { name: 'Preview workspace.json', exact: true }),
    ).toHaveCount(0);
    await expect(
      contents(page).getByRole('button', { name: 'Open Documents', exact: true }),
    ).toBeVisible();
    const fileCard = contents(page)
      .locator('[data-node]')
      .filter({ has: page.getByRole('button', { name: 'Open Budget.csv', exact: true }) });
    const fileBounds = await fileCard.boundingBox();
    await fileCard.hover();
    const heading = (await fileCard.locator('.storage-item-heading').boundingBox())!;
    const preview = (await fileCard.locator('.storage-item-preview').boundingBox())!;
    expect(heading.y + heading.height).toBeLessThanOrEqual(preview.y);
    const menuButton = (await fileCard
      .getByRole('button', { name: 'Actions for Budget.csv', exact: true })
      .boundingBox())!;
    expect(menuButton.y).toBeGreaterThanOrEqual(heading.y);
    expect(menuButton.y + menuButton.height).toBeLessThanOrEqual(heading.y + heading.height);
    expect(await fileCard.boundingBox()).toEqual(fileBounds);
    if (dir)
      await page.screenshot({
        path: resolve(dir, `storage-file-hover-${width}.png`),
        animations: 'disabled',
      });

    if (width <= 720) {
      await page.getByRole('button', { name: 'Workspace', exact: true }).click();
      await expect(
        page.getByRole('navigation', { name: 'Storages', exact: true }).getByRole('separator'),
      ).toHaveCount(1);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
}

test('Drive cards show file-type icons and preserve bounds through view changes and resize', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1452, height: 886 });
  await page.goto('/app?view=storage');
  await page
    .getByRole('navigation', { name: 'Storages', exact: true })
    .getByRole('button', { name: 'Team', exact: true })
    .click();
  const fixtures = [
    ['Brief.pdf', 'application/pdf', 'pdf'],
    [
      'Budget.xlsx',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'spreadsheet',
    ],
    ['Slides.pptx', '', 'presentation'],
    ['Photo.png', '', 'image'],
    ['Clip.mp4', '', 'video'],
    ['Recording.wav', '', 'audio'],
    ['Backup.zip', '', 'archive'],
    ['Config.json', 'application/json', 'code'],
    ['zip-guide.txt', 'text/plain', 'document'],
    ['Unknown.bin', 'application/octet-stream', 'file'],
  ];
  await page
    .getByLabel('Upload files', { exact: true })
    .setInputFiles(
      fixtures.map(([name, mimeType]) => ({ name, mimeType, buffer: Buffer.from('Icon fixture') })),
    );
  for (const [name, , type] of fixtures) {
    await expect(
      contents(page)
        .getByRole('button', { name: `Open ${name}`, exact: true })
        .locator('.storage-item-heading svg'),
    ).toHaveAttribute('data-file-type', type);
  }
  await expect(contents(page).getByRole('checkbox')).toHaveCount(0);
  for (const width of [1452, 721, 390, 1452]) {
    await page.setViewportSize({ width, height: 886 });
    for (const view of ['Grid', 'Mosaic', 'List']) {
      await page.getByRole('radio', { name: view, exact: true }).click();
      await contents(page).getByRole('button', { name: 'Open Images', exact: true }).hover();
      await page.getByRole('button', { name: 'Actions for Images', exact: true }).focus();
      const clipped = await page.locator('.storage-page').evaluate((element) => {
        const result = [];
        for (let node = element; node; node = node.parentElement!) {
          const bounds = node.getBoundingClientRect();
          if (bounds.x < -1 || bounds.right > innerWidth + 1 || node.scrollLeft !== 0)
            result.push({
              className: node.className,
              x: bounds.x,
              right: bounds.right,
              scrollLeft: node.scrollLeft,
            });
        }
        return result;
      });
      expect(clipped).toEqual([]);
    }
  }
});
