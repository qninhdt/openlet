import { expect, test } from '@playwright/test';
import { safeReturnTo } from '../src/lib/auth-navigation.js';

test('sign-in return URLs keep workspace and invite links on this origin', () => {
  for (const invalid of [
    'https://example.com',
    '//example.com',
    '/\\example.com',
    '/app\nhttps://example.com',
    '/app/../../login',
    '/privacy',
    undefined,
  ])
    expect(safeReturnTo(invalid)).toBe('/app');
  for (const path of [
    '/app/abc/agents/def/activity',
    '/app/abc/storage/files/file?version=2#notes',
    '/workspaces',
    '/join?token=private',
  ])
    expect(safeReturnTo(path)).toBe(path);
});
