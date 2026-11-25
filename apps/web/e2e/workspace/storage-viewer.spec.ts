import { expect, test, workspace } from '../fixtures/browser';

const storage = '00000000-0000-4000-8000-000000000011';
const root = '00000000-0000-4000-8000-000000000012';
const folder = '00000000-0000-4000-8000-000000000013';
const image = '00000000-0000-4000-8000-000000000014';
const text = '00000000-0000-4000-8000-000000000015';

test('file viewers use one toolbar, keep browser breadcrumbs and expose processing details on demand', async ({
  page,
}) => {
  let retries = 0;
  const remote = (id: string) => ({
    id,
    storageId: storage,
    parentId: id === root ? undefined : id === folder ? root : folder,
    name: id === root ? '' : id === folder ? 'Documents' : id === image ? 'photo.svg' : 'notes.md',
    kind: id === root || id === folder ? 'NODE_KIND_DIRECTORY' : 'NODE_KIND_FILE',
    updatedAt: '2026-11-18T00:00:00Z',
    ...(id === image || id === text
      ? {
          file: {
            type: id === text ? 'FILE_TYPE_TEXT' : 'FILE_TYPE_BLOB',
            mediaType: id === image ? 'image/svg+xml' : 'text/markdown',
            sizeBytes: '120',
            version: '1',
            processing:
              id === image
                ? { stage: 'queued', ...(!retries ? { errorCode: 'PARSE_FAILED' } : {}) }
                : { stage: 'ready' },
          },
        }
      : {}),
  });
  await page.route(`**/v1/workspaces/${workspace}/storage-quota`, (route) =>
    route.fulfill({ json: { usedBytes: '240', quotaBytes: '10000' } }),
  );
  await page.route(`**/v1/workspaces/${workspace}/storages**`, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/storages'))
      return route.fulfill({
        json: {
          storages: [
            { id: storage, name: 'Team', rootNodeId: root, capabilities: { write: true } },
          ],
        },
      });
    const id = url.pathname.split('/nodes/')[1]?.split(/[/:]/)[0];
    if (!id) return route.fulfill({ status: 404, json: {} });
    if (url.pathname.endsWith(':retryProcessing')) {
      retries++;
      return route.fulfill({ json: remote(id) });
    }
    if (url.pathname.endsWith(':download'))
      return route.fulfill({
        json: {
          text: {
            content:
              id === text
                ? '# Viewer fixture\n\nEditable notes.\n'
                : '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="700"><rect width="1000" height="700" fill="#abc8bf"/><circle cx="500" cy="350" r="180" fill="#648879"/></svg>',
            mediaType: id === text ? 'text/markdown' : 'image/svg+xml',
          },
        },
      });
    if (url.pathname.endsWith('/children'))
      return route.fulfill({
        json: { nodes: id === root ? [remote(folder)] : [remote(image), remote(text)] },
      });
    return route.fulfill({ json: remote(id) });
  });
  await page.goto(`/app/${workspace}/storage/${storage}/files/${image}`);
  const viewer = page.getByRole('region', { name: 'Preview photo.svg' });
  await expect(viewer.getByRole('img')).toBeVisible();
  await expect(viewer.locator('.storage-viewer-head')).toHaveCount(1);
  await expect(page.getByRole('navigation', { name: 'Storage path' })).toHaveCount(0);
  await expect(page.getByRole('tab', { name: 'photo.svg', exact: true })).toHaveAttribute(
    'title',
    '/Team/Documents/photo.svg',
  );
  const dot = viewer.getByRole('button', { name: 'File processing failed (PARSE_FAILED).' });
  await dot.hover();
  await expect(page.getByRole('tooltip')).toContainText('PARSE_FAILED');
  await dot.click();
  await page.getByRole('button', { name: 'Retry processing' }).click();
  await expect(viewer.getByRole('button', { name: 'Queued for processing…' })).toBeVisible();
  expect(retries).toBe(1);
  await page.keyboard.press('Escape');
  await expect(viewer).toBeVisible();
  await viewer.getByRole('button', { name: 'Zoom in', exact: true }).click();
  await expect(viewer).toContainText('125%');
  await viewer.getByRole('button', { name: 'Fit image' }).click();
  await expect(viewer).toContainText('100%');
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(viewer.getByRole('button', { name: 'Download file' })).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(
      false,
    );
    await page.screenshot({ path: `/tmp/storage-image-${width}.png` });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('tab', { name: 'Team', exact: true }).click();
  await expect(page.getByRole('navigation', { name: 'Storage path' })).toBeVisible();
  await page.goto(`/app/${workspace}/storage/${storage}/files/${text}`);
  const editor = page.getByRole('region', { name: 'Preview notes.md' });
  await expect(editor.getByRole('heading', { name: 'Viewer fixture' })).toBeVisible();
  await expect(editor.locator('.storage-viewer-head')).toHaveCount(1);
  await expect(page.getByRole('navigation', { name: 'Storage path' })).toHaveCount(0);
  await editor.getByRole('button', { name: 'File processing complete' }).hover();
  await expect(page.getByRole('tooltip')).toContainText('File processing complete');
  await page.mouse.move(0, 0);
  await editor.getByRole('tab', { name: 'Code', exact: true }).click();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(editor.getByRole('button', { name: 'Download file' })).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(
      false,
    );
    await page.screenshot({ path: `/tmp/storage-text-${width}.png` });
  }
});
