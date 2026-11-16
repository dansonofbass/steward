import { expect, test } from '@playwright/test';
import { loginAs, restoreVault } from './fixtures';

// Spec 2026-11-05, section 7: a household of one offers Person 1 (its one person's name), Joint and Business only.
test.beforeAll(async () => { await restoreVault(); });

test('the owner picker offers the one person, Joint and Business', async ({ page }) => {
  await loginAs(page, 'casey', 'pw-solo-demo-2026');
  const books = (await (await page.request.get('/api/books')).json()).books as { slug: string; name: string }[];
  const slug = books.find((b) => b.name === 'Solo')!.slug;
  const me = await (await page.request.get('/api/auth/me')).json();
  expect(me.books.find((b: { slug: string }) => b.slug === slug).owners.map((o: { label: string }) => o.label))
    .toEqual(['Casey Moreau', 'Joint', 'Business']);
  await page.goto(`/b/${slug}/accounts`);
  await page.getByRole('button', { name: 'Add an account' }).click();
  await page.getByRole('button', { name: /One you update manually/ }).click();
  await expect(page.getByLabel('Owner').locator('option')).toHaveText(['Casey Moreau', 'Joint', 'Business']);
});
