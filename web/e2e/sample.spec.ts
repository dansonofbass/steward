import { expect, test } from '@playwright/test';
import { loginAs, restoreVault, tab, youMenu } from './fixtures';

// The Sample book (guided setup spec 8): made from the welcome replay, framed by a ribbon, refused what reaches a bank,
// a file or Claude, and removed with an Undo. Serial: each test builds on the one before.
test.describe.configure({ mode: 'serial' });
test.beforeAll(async () => { await restoreVault(); });

test('look around from the welcome replay, with the ribbon everywhere and Ask off', async ({ page }) => {
  await loginAs(page, 'alex');
  await page.goto('/');
  await youMenu(page);
  await page.getByRole('link', { name: 'Help' }).click();
  await page.getByRole('link', { name: 'See the welcome again' }).click();
  await page.getByRole('button', { name: 'Look around with a sample household first' }).click();
  await expect(page).toHaveURL(/\/b\/sample$/);
  for (const path of ['', '/spending', '/plan', '/transactions', '/review', '/settings']) {
    await page.goto(`/b/sample${path}`);
    await expect(page.getByRole('note').filter({ hasText: 'Sample' })).toBeVisible();
  }
  await page.goto('/b/sample');
  await tab(page, 'Ask').click();
  await expect(page.getByText('Ask is off in the Sample.')).toBeVisible();
  await page.getByRole('button', { name: /^Switch book/ }).click();
  await expect(page.getByRole('link', { name: 'Sample Made-up money' })).toBeVisible();
});

test('imports are refused in code', async ({ page }) => {
  await loginAs(page, 'alex');
  const r = await page.request.post('/api/b/sample/import/files', { data: 'Date,Description,Amount\n', headers: { 'Content-Type': 'text/csv', 'X-Filename': 'x.csv' } });
  expect(r.status()).toBe(403);
  expect((await r.json()).error).toBe("The Sample book is for looking around. It doesn't do that.");
});

test('Remove, Undo, Remove', async ({ page }) => {
  await loginAs(page, 'alex');
  await page.goto('/b/sample');
  await page.getByRole('note').getByRole('button', { name: 'Remove the Sample' }).click();
  await expect(page).toHaveURL(/\/b\/ours$/);
  await expect(page.getByText('Sample removed')).toBeVisible();
  await page.getByRole('button', { name: 'Undo' }).click();
  await expect(page).toHaveURL(/\/b\/sample$/);
  await expect(page.getByRole('note').filter({ hasText: 'Sample' })).toBeVisible();
  await page.getByRole('note').getByRole('button', { name: 'Remove the Sample' }).click();
  await expect(page).toHaveURL(/\/b\/ours$/);
  // With the Sample gone the switcher (alex has other books) offers none, and /me no longer lists one.
  await page.getByRole('button', { name: /^Switch book/ }).click();
  await expect(page.getByRole('link', { name: /^Ours/ })).toBeVisible();
  await expect(page.getByText('Made-up money')).toHaveCount(0);
  const me = await (await page.request.get('/api/auth/me')).json();
  expect(me.books.some((b: { slug: string }) => b.slug === 'sample')).toBe(false);
});
