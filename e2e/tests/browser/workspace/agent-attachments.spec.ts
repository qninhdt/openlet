import { agent, expect, test, workspace } from '../../../fixtures/browser.js';

const storage = '00000000-0000-4000-8000-000000000001';
const ids = {
  report: '00000000-0000-4000-8000-000000000002',
  first: '00000000-0000-4000-8000-000000000003',
  second: '00000000-0000-4000-8000-000000000004',
  unavailable: '00000000-0000-4000-8000-000000000005',
};
const ref = (node_id: string, label: string, mime = 'text/plain') => ({
  storage_id: storage,
  node_id,
  label,
  mime,
});

test('mentions stay inline; explicit attachments support albums, file-only messages, preview and download', async ({
  page,
}) => {
  let sentMessages = 0;
  await page.route('**/messages/read', (route) => route.fulfill({ json: {} }));
  await page.route('**/processing', (route) =>
    route.fulfill({ json: { working: false, run_id: null } }),
  );
  await page.route('**/messages?*', async (route) => {
    if (route.request().method() !== 'GET') {
      sentMessages++;
      return route.fulfill({ status: 400, json: { detail: 'This test never sends messages' } });
    }
    const fixtures = [
      {
        id: 'mention',
        content: `Xem :file[Báo cáo]{name=${storage}/${ids.report}}`,
        file_refs: [],
      },
      {
        id: 'album',
        content: 'Hai ảnh đây.',
        file_refs: [
          ref(ids.first, 'one.png', 'image/png'),
          ref(ids.second, 'two.png', 'image/png'),
          ref(ids.first, 'one.png', 'image/png'),
        ],
      },
      { id: 'file-only', content: '', file_refs: [ref(ids.report, 'report.txt')] },
      {
        id: 'unavailable',
        content: 'File không còn khả dụng.',
        file_refs: [ref(ids.unavailable, 'unavailable.txt')],
      },
    ]
      .map((message, index) => ({
        ...message,
        role: 'assistant',
        created_at: new Date(Date.now() + index * 1000).toISOString(),
      }))
      .reverse();
    await route.fulfill({ json: { items: fixtures, next_cursor: null } });
  });
  await page.route(`**/storages/${storage}/nodes/**`, async (route) => {
    const url = new URL(route.request().url());
    const id = url.pathname.split('/nodes/')[1].split(/[/:]/)[0];
    if (id === ids.unavailable)
      return route.fulfill({ status: 404, json: { detail: 'File unavailable' } });
    const imageContent = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="${id === ids.first ? '#b0d5d0' : '#e3c6ab'}"/><circle cx="320" cy="240" r="120" fill="${id === ids.first ? '#658b7f' : '#b27e5c'}"/></svg>`;
    if (url.pathname.endsWith(':download'))
      return route.fulfill({
        json: {
          text: {
            content: id === ids.report ? 'Attachment fixture' : imageContent,
            mediaType: id === ids.report ? 'text/plain' : 'image/svg+xml',
          },
        },
      });
    if (url.pathname.endsWith('/image'))
      return route.fulfill({
        contentType: 'image/svg+xml',
        body: imageContent,
      });
    const image = id !== ids.report;
    return route.fulfill({
      json: {
        id,
        storageId: storage,
        parentId: 'fixture-root',
        name: image ? (id === ids.first ? 'one.png' : 'two.png') : 'report.txt',
        kind: 'NODE_KIND_FILE',
        file: {
          mediaType: image ? 'image/png' : 'text/plain',
          sizeBytes: '18',
          version: '1',
          type: image ? 'FILE_TYPE_BLOB' : 'FILE_TYPE_TEXT',
        },
        updatedAt: '2026-11-18T00:00:00Z',
      },
    });
  });
  await page.goto(`/app/${workspace}/agents/${agent}?role=user`);
  await page.getByRole('textbox', { name: /^Message / }).waitFor();
  const mention = page.locator('#chat-assistant-mention');
  await expect(mention.getByRole('button', { name: 'Báo cáo', exact: true })).toBeVisible();
  await expect(mention.getByLabel('Attached files')).toHaveCount(0);
  await expect(mention).not.toContainText(':file[');
  const album = page.locator('#chat-assistant-album');
  await expect(album.getByRole('button', { name: /^Preview / })).toHaveCount(2);
  await expect(album.getByRole('button', { name: /^Download / })).toHaveCount(0);
  await expect(album).not.toContainText('one.png');
  await expect(album).not.toContainText('two.png');
  const only = page.locator('#chat-assistant-file-only');
  await expect(only.locator('[data-slot=bubble]')).toHaveCount(0);
  await expect(only.getByRole('button', { name: 'Download report.txt' })).toBeEnabled();
  const downloading = page.waitForEvent('download');
  await only.getByRole('button', { name: 'Download report.txt' }).click();
  expect((await downloading).suggestedFilename()).toBe('report.txt');
  await expect(
    page
      .locator('#chat-assistant-unavailable')
      .getByRole('button', { name: 'Download unavailable.txt' }),
  ).toBeDisabled();
  await expect(page.locator('#chat-assistant-unavailable')).toContainText('Unavailable');
  for (const [width, height] of [
    [1440, 1000],
    [390, 844],
  ]) {
    await page.setViewportSize({ width, height });
    await expect(() => album.scrollIntoViewIfNeeded()).toPass();
    const boxes = await album.getByRole('button', { name: /^Preview / }).evaluateAll((elements) =>
      elements.map((element) => ({
        x: element.getBoundingClientRect().x,
        y: element.getBoundingClientRect().y,
      })),
    );
    expect(Math.abs(boxes[0].y - boxes[1].y)).toBeLessThan(2);
    expect(boxes[1].x).toBeGreaterThan(boxes[0].x);
    for (const preview of await album.getByRole('button', { name: /^Preview / }).all()) {
      const clipped = await preview.evaluate((element) => {
        const bounds = element.getBoundingClientRect();
        const attachment = element
          .closest('[aria-label="Attached files"]')!
          .getBoundingClientRect();
        return (
          bounds.right > attachment.right ||
          bounds.left < attachment.left ||
          !!element.closest('[data-slot=bubble-content]')
        );
      });
      expect(clipped).toBe(false);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(
      false,
    );
    await page.screenshot({ path: `/tmp/agent-attachments-${width}.png` });
    await album.getByRole('button', { name: 'Preview one.png' }).click();
    const gallery = page.getByRole('dialog', { name: 'Message photos' });
    await expect(gallery).toBeVisible();
    await expect(gallery.getByRole('button', { name: 'Previous image' })).toBeDisabled();
    await expect(gallery.getByRole('img', { name: 'one.png', exact: true })).toBeVisible();
    await gallery.getByRole('button', { name: 'Next image' }).click();
    await expect(gallery.getByRole('button', { name: 'Next image' })).toBeDisabled();
    await expect(gallery.getByRole('img', { name: 'two.png', exact: true })).toBeVisible();
    await expect
      .poll(() =>
        gallery.getByRole('img', { name: 'two.png', exact: true }).evaluate((image) => {
          const bounds = image.getBoundingClientRect();
          return (
            bounds.left >= 0 &&
            bounds.right <= innerWidth &&
            (image as HTMLImageElement).naturalWidth > 0
          );
        }),
      )
      .toBe(true);
    await page.screenshot({ path: `/tmp/agent-gallery-${width}.png` });
    await gallery.press('ArrowLeft');
    await expect(gallery.getByRole('button', { name: 'Previous image' })).toBeDisabled();
    await page.keyboard.press('Escape');
    await expect(gallery).toHaveCount(0);
  }
  await mention.getByRole('button', { name: 'Báo cáo', exact: true }).click();
  await expect(page.getByText('Attachment fixture', { exact: true })).toBeVisible();
  expect(sentMessages).toBe(0);
});
