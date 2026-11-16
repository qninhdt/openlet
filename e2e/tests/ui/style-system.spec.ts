import { expect, test } from '@playwright/test';
import { cn } from '../../../apps/web/src/lib/utils.js';

test('custom typography tokens preserve semantic colors when component classes merge', () => {
  for (const size of ['caption', 'agent']) {
    for (const color of ['text-primary-foreground', 'text-muted-foreground', 'text-destructive']) {
      const classes = cn(`text-sm ${color}`, `text-${size}`).split(' ');
      expect(classes).toContain(color);
      expect(classes).toContain(`text-${size}`);
      expect(classes).not.toContain('text-sm');
      expect(cn(`text-${size} ${color}`, 'text-sm')).toBe(`${color} text-sm`);
    }
  }
});
