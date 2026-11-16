import { expect, test, type Page } from '@playwright/test';
import { listView, loginAs, restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

// Bulk sort (profile spec, Sorting several rows at once): Select, pick rows, Sort as…, the result line, Undo. Each test
// undoes its own sort, so the demo household is as it was for the specs after it.

const sortAs = async (page: Page, words: string, name: string) => {
  await page.getByTestId('bulk-bar').getByRole('button', { name: 'Sort as…' }).click();
  await page.getByRole('combobox', { name: 'Find a category' }).fill(words);
  await page.getByRole('dialog', { name: 'Sort as…' }).getByRole('option', { name, exact: true }).click();
};

test('Review: three cards sorted at once become slim rows in place, and one Undo brings them all back', async ({ page }) => {
  await loginAs(page, 'spouse');
  await page.goto('/review');
  await listView(page);
  const fresh = page.locator('[data-testid=review-card]');
  await expect(fresh.nth(3)).toBeVisible();
  const before = (await (await page.request.get('/api/b/ours/review')).json()).count as number;
  await page.getByRole('button', { name: 'Select', exact: true }).click();
  await expect(page.getByTestId('bulk-bar')).toContainText('0 selected');
  const ids = await Promise.all([0, 1, 2].map((i) => fresh.nth(i).getAttribute('data-id')));
  const card = (id: string | null) => page.locator(`[data-testid=review-card][data-id="${id}"]`);
  // Each card is a compact row while selecting: the pick box, never the sorting controls.
  await expect(card(ids[0])).toHaveClass(/is-compact/);
  await expect(card(ids[0]).locator('.chips, .rcard__foot')).toHaveCount(0);
  await card(ids[0]).click();
  await card(ids[1]).locator('.rcard__pick').check();
  await card(ids[2]).click();
  await expect(page.getByTestId('bulk-bar')).toContainText('3 selected');
  await sortAs(page, 'gift', 'Gifts');
  const said = page.getByTestId('bulk-said');
  await expect(said).toContainText('Sorted 3 as Gifts');
  await expect(page.getByTestId('bulk-bar')).toHaveCount(0);
  for (const id of ids) await expect(page.locator(`[data-testid=slim-row][data-id="${id}"]`)).toContainText('SORTED · ');
  expect((await (await page.request.get('/api/b/ours/review')).json()).count).toBe(before - 3);
  await said.getByRole('button', { name: 'Undo' }).click();
  await expect(said).toContainText('Undone.');
  for (const id of ids) await expect(card(id)).toBeVisible();
  expect((await (await page.request.get('/api/b/ours/review')).json()).count).toBe(before);
});

test('Transactions: Shift-click picks a range, the rows take the category, and Undo restores them', async ({ page }, testInfo) => {
  await loginAs(page, 'alex');
  await page.goto('/transactions?dates=all&q=SQ%20*VENDOR');
  const rows = page.locator('[data-testid=txn-row]');
  await expect(rows.nth(2)).toBeVisible();
  const was = (await (await page.request.get('/api/b/ours/transactions?q=SQ%20*VENDOR&limit=3')).json()).transactions
    .map((t: { id: number; category: string }) => [t.id, t.category]);
  await page.getByRole('button', { name: 'Select', exact: true }).click();
  await rows.nth(0).click();
  if (testInfo.project.name === 'phone') {
    await rows.nth(1).click();
    await rows.nth(2).click();
  } else {
    await rows.nth(2).click({ modifiers: ['Shift'] });
  }
  await expect(page.getByTestId('bulk-bar')).toContainText('3 selected');
  await expect(rows.nth(1)).toHaveAttribute('aria-checked', 'true');
  await sortAs(page, 'kids', 'Kids');
  const said = page.getByTestId('bulk-said');
  await expect(said).toContainText('Sorted 3 as Kids');
  const now = async () => (await (await page.request.get('/api/b/ours/transactions?q=SQ%20*VENDOR&limit=3')).json()).transactions
    .map((t: { id: number; category: string }) => [t.id, t.category]);
  expect(await now()).toEqual(was.map(([id]: [number]) => [id, 'kids']));
  await expect(rows.nth(0)).toContainText('Kids');
  await said.getByRole('button', { name: 'Undo' }).click();
  await expect(said).toContainText('Undone.');
  expect(await now()).toEqual(was);
});
