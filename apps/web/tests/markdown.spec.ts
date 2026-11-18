import { expect, test } from '@playwright/test';
import { mathMarkdown } from '../src/lib/markdown.js';

const inline = String.raw`\(y=\dfrac{x-1}{x+2}\)`;

test('TeX delimiters normalize without changing literal code or dollar math', () => {
  expect(mathMarkdown(`Hàm số ${inline}.`)).toBe(String.raw`Hàm số $y=\dfrac{x-1}{x+2}$.`);
  expect(mathMarkdown(String.raw`\[\boxed{2\sqrt{3}}\]`)).toBe(
    '\n$$\n' + String.raw`\boxed{2\sqrt{3}}` + '\n$$\n',
  );
  for (const source of [
    `$x^2$ and $$\nx^2\n$$`,
    '`' + inline + '`',
    '``' + inline + '`sample``',
    '```latex\n' + inline + '\n```',
    '~~~text\n' + inline + '\n~~~',
    '```text\n' + inline,
    String.raw`\\(literal\\)`,
    String.raw`\(unfinished`,
    String.raw`\(\)`,
  ])
    expect(mathMarkdown(source)).toBe(source);
});
