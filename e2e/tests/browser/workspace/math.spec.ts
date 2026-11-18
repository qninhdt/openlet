import { agent, expect, test, workspace } from '../../../fixtures/browser.js';

const inline = String.raw`\(y=\dfrac{x-1}{x+2}\)`;

test('chat renders inline and display math, keeps code literal and contains wide formulas on mobile', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const message = [
    `Mình đọc đề là: Cho hàm số ${inline}. Gọi \\(I\\) là giao điểm hai tiệm cận.`,
    String.raw`Đặt \(a=\sqrt{6-3\sqrt3}\), \(b=\sqrt{6+3\sqrt3}\). Kết quả \(\boxed{A(-2+a;1-b)}\).`,
    String.raw`Ta có $uv=-3$, suy ra \(\boxed{A(-2+\sqrt{6-3\sqrt{3}};1-\sqrt{6+3\sqrt{3}}),\quad B(-2+\sqrt{6+3\sqrt{3}};1-\sqrt{6-3\sqrt{3}})}\).`,
    String.raw`\[\overrightarrow{IA}\cdot\overrightarrow{IB}=\frac{IA^2}{2}>0\]`,
    '$$\n' +
      String.raw`\underbrace{a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a}_{20\text{ terms}}=20a` +
      '\n$$',
    'Literal `' + inline + '`',
    '```text\n' + inline + '\n```',
    String.raw`Lỗi cú pháp vẫn đọc được: $\frac{$`,
    String.raw`Liên kết không tin cậy: $\href{javascript:alert(1)}{x}$`,
  ].join('\n\n');
  await page.route(`**/v1/workspaces/${workspace}/letas/${agent}/messages?*`, (route) =>
    route.fulfill({
      json: {
        items: [
          { id: 'math-user', role: 'user', content: message, created_at: '2026-11-18T00:00:00Z' },
        ],
        next_cursor: null,
      },
    }),
  );
  await page.goto(`/app/${workspace}/agents/${agent}`);
  const article = page
    .locator('[aria-label="Atlas private chat"] article')
    .filter({ hasText: 'Mình đọc đề là:' });
  await expect(article).toHaveCount(1);
  await expect(article.locator('.katex')).toHaveCount(10);
  await expect(article.locator('.katex-display')).toHaveCount(2);
  await expect(article.locator('math')).toHaveCount(10);
  await expect(article.locator('.katex-error')).toHaveCount(1);
  await expect(article.locator('p code')).toHaveText(inline);
  await expect(article.locator('pre[aria-label="text code"]')).toHaveText(inline);
  await expect(article.locator('a[href^="javascript:"]')).toHaveCount(0);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.evaluate(() => document.fonts.ready);
    const shortMath = article.locator('p').filter({ hasText: 'Đặt' }).locator('.katex');
    expect(
      await shortMath.evaluateAll((formulas) =>
        formulas.every((element) => element.scrollWidth <= element.clientWidth),
      ),
    ).toBe(true);
    const overflow = await article.evaluate((element) => {
      const bubble = element.closest('[data-slot=bubble-content]')!.getBoundingClientRect();
      return [...element.querySelectorAll('.katex-display, p > .katex, p')].some(
        (child) => child.getBoundingClientRect().right > bubble.right + 1,
      );
    });
    expect(overflow).toBe(false);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(
      false,
    );
    if (width === 390) {
      const wide = article.locator('.katex-display').last();
      await wide.press('ArrowRight');
      await expect.poll(() => wide.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
      await wide.evaluate((element) => {
        element.scrollLeft = 0;
      });
    }
  }
});
