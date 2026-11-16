import { expect, test } from '@playwright/test';
import { loginAs, tab, restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

test.beforeEach(async ({ page }) => { await loginAs(page, 'alex'); });

test('an account on the Accounts tab opens its own transactions, a transaction opens and closes, and Back returns', async ({ page }, info) => {
  // Every transactions request the account page makes, to check it asks for this account's rows only.
  const asked: URL[] = [];
  page.on('request', (r) => { if (/\/api\/b\/ours\/transactions(\?|$)/.test(r.url())) asked.push(new URL(r.url())); });

  await page.goto('/');
  await tab(page, 'Accounts').click();
  await expect(page.getByRole('heading', { name: 'Accounts', level: 1 })).toBeVisible();
  await page.getByRole('region', { name: 'Cash' }).getByRole('link', { name: /^Checking/ }).click();
  await expect(page).toHaveURL(/\/b\/ours\/accounts\/\d+$/);
  const id = page.url().match(/\/accounts\/(\d+)$/)![1];
  await expect(page.getByRole('heading', { name: 'Checking', level: 1 })).toBeVisible();
  await expect(page.getByRole('main').getByRole('link', { name: 'Accounts', exact: true })).toHaveAttribute('href', '/b/ours/accounts');

  // The demo's rows end on a fixed date, so widen the dates to see them.
  await page.getByRole('button', { name: /^Dates/ }).click();
  await page.getByRole('dialog', { name: 'Dates' }).getByRole('radio', { name: 'All time' }).click();
  await expect(page).toHaveURL(new RegExp(`/accounts/${id}\\?dates=all$`));
  const rows = page.getByTestId('txn-row');
  await expect(rows.first()).toBeVisible();
  for (const row of (await rows.all()).slice(0, 10)) await expect(row).toContainText('Checking ·');
  expect(asked.length).toBeGreaterThan(0);
  for (const u of asked) expect(u.searchParams.get('account_id')).toBe(id);

  // A sheet on the phone, the side pane on a laptop; closing it puts focus back on the row.
  const row = rows.first();
  await row.click();
  const detail = page.getByTestId('txn-detail');
  await expect(detail).toBeVisible();
  if (info.project.name === 'phone') {
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
  } else {
    await detail.getByRole('button', { name: 'Close' }).click();
  }
  await expect(detail).toHaveCount(0);
  await expect(row).toBeFocused();
  await expect(page).toHaveURL(new RegExp(`/accounts/${id}\\?dates=all$`));

  // Back undoes the dates, then returns to the Accounts tab. The page opened on the range it chose for itself: with
  // web/e2e/seed_notes.py's PayPal charge three days old the week is not empty, so it stays on its own, and Back lands there.
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`/b/ours/accounts/${id}$`));
  await page.goBack();
  await expect(page).toHaveURL(/\/b\/ours\/accounts$/);
  await expect(page.getByRole('heading', { name: 'Accounts', level: 1 })).toBeVisible();
});

test('the Accounts tab lays out as a page: its cards stack their rows and nothing runs past the window', async ({ page }) => {
  // Every screen's CSS is on the page at once, so a class another screen also styles (".kind" in Inventory once made
  // each card a flex row: names one letter per line, the page wider than the window, the rail scrolled off).
  await page.goto('/');
  await tab(page, 'Accounts').click();
  const cash = page.getByRole('region', { name: 'Cash' });
  const links = cash.getByRole('link');
  await expect(links.nth(1)).toBeVisible();
  const [a, b] = [await links.nth(0).boundingBox(), await links.nth(1).boundingBox()];
  expect(b!.y).toBeGreaterThanOrEqual(a!.y + a!.height - 1);       // one under the other, not side by side
  expect(a!.width).toBeGreaterThan(200);                            // a row is a row, not a column of letters
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("Accounts shows the plan's tax mix and net worth over time below the cards, the chart in its own chunk", async ({ page }) => {
  const chunks: string[] = [];
  page.on('request', (r) => { if (/\/NetWorthChart-[\w-]+\.js$/.test(r.url())) chunks.push(r.url()); });
  await page.goto('/accounts');
  await expect(page.getByRole('heading', { name: "Your money, by how it's taxed" })).toBeVisible();
  await expect(page.getByText('Counted in the plan')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Net worth over time' })).toBeVisible();
  await expect(page.locator('svg.nw-chart:visible')).toHaveCount(1);
  expect(chunks).toHaveLength(1);
});
