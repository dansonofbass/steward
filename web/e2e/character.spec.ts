import { expect, test } from '@playwright/test';
import { loginAs, restoreVault } from './fixtures';

// Phase 17 spec 3.9: Review's sort toast with a cheer and Undo intact, All caught up's acorn, and none for an empty book
// (the review answer's `empty`, ruling R4). (A parent book's lack
// of faces is the last test, added in Task 8.)
test.beforeAll(async () => { await restoreVault(); });

for (const size of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) test(`the 4th sort cheers in the toast, which keeps Undo whole on the screen at ${size.width}`, async ({ page }) => {
  await page.setViewportSize(size);
  await page.addInitScript(() => { Math.random = () => 0.5; });   // never golden; a cheer every 4th sort
  // Review's sort cheer is quiet in a red month (claim T6), and whether the demo's month is red depends on today's
  // date. This test is about the toast's layout with a cheer in it, so Home's answer reads as a month in the black.
  await page.route(/\/api\/b\/[^/]+\/home$/, async (route) => {
    const response = await route.fetch();
    const json = await response.json();
    json.flow.net_cents = Math.abs(json.flow.net_cents) + 100;
    if (json.verdict.opener === 'problem') json.verdict.opener = 'steady';
    await route.fulfill({ response, json });
  });
  await loginAs(page, 'spouse');
  await page.goto('/review');
  const card = page.locator('[data-testid=focus-card][data-role=current]');
  for (let i = 0; i < 4; i++) {
    const id = await card.getAttribute('data-id');
    const also = card.getByRole('checkbox', { name: /^Also the / });
    if (await also.count()) await also.uncheck();
    await card.locator('.chips button:not(.chip--more)').first().click();
    await expect(card).not.toHaveAttribute('data-id', id!);
    if (i < 3) await expect(page.getByTestId('toast-cheer')).toHaveCount(0);
  }
  const toast = page.locator('.undo-toast');
  await expect(toast).toContainText('SORTED');
  await expect(toast.getByRole('button', { name: 'Undo' })).toBeInViewport({ ratio: 1 });
  await expect(page.getByTestId('toast-cheer')).toBeInViewport({ ratio: 1 });   // its own row: shown whole at 390 and 1280
});

test('All caught up rests the acorn on its horizon with a line', async ({ page }) => {
  await loginAs(page, 'alex');
  await page.route(/\/api\/b\/ours\/review$/, (r) => r.fulfill({ json: {
    uncategorized: [], count: 0, sorted_count: 0, duplicates: [], duplicate_count: 0, top_categories: [], business: [], business_count: 0,
    background: { pending: 0, done: 0, waiting: false }, empty: false } }));
  await page.goto('/review');
  await expect(page.locator('.review__horizon svg.acorn')).toHaveAttribute('data-face', /resting|golden/);
  await expect(page.getByTestId('caught-up-line')).toBeVisible();
});

test("an empty book's Review shows no acorn and no caughtUp line (ruling R4)", async ({ page }) => {
  await loginAs(page, 'alex');
  await page.route(/\/api\/b\/ours\/review$/, (r) => r.fulfill({ json: {
    uncategorized: [], count: 0, sorted_count: 0, duplicates: [], duplicate_count: 0, top_categories: [], business: [], business_count: 0,
    background: { pending: 0, done: 0, waiting: false }, empty: true } }));
  await page.goto('/review');
  await expect(page.getByRole('main').getByText('Nothing here yet. Import a file and Steward starts sorting.')).toBeVisible();
  await expect(page.locator('svg.acorn')).toHaveCount(0);
  await expect(page.getByTestId('caught-up-line')).toHaveCount(0);
});

test('a parent book shows no face and no tree anywhere (spec 3.5)', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', "the desktop project's parent book");
  await loginAs(page, 'alex');
  for (const path of ['', '/review', '/transactions', '/settings/import', '/inventory']) {
    await page.goto(`/b/margaret-ellis-seed-desktop${path}`);
    await page.waitForFunction(() => !document.querySelector('.skeleton, [aria-busy="true"]'));
    await expect(page.locator('svg.acorn'), path || 'home').toHaveCount(0);
    await expect(page.locator('svg.oak'), path || 'home').toHaveCount(0);
  }
});
