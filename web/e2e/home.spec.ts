import { expect, test, type Page } from '@playwright/test';
import { dollars } from '../src/lib/format';
import { loginAs, restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2). web/e2e/seed_home.py gives alex
// a last look three days back, and a paycheck, a Bill and a large charge after it.
test.beforeAll(async () => { await restoreVault(); });
test.beforeEach(async ({ page }) => { await loginAs(page, 'alex'); });

type Head = { head: { money_out_cents: number; money_in_cents: number } };
const ready = (page: Page) => page.getByTestId('verdict').and(page.locator('[data-ready=true]'));
const SYNC = 'Big Bank needs you to sign in again at SimpleFIN';

test('Since lists what came in after the last look, and the headline and the figure say what Spending says', async ({ page }) => {
  await page.goto('/');
  await expect(ready(page)).toBeVisible();
  const since = page.getByTestId('since');
  await expect(since.getByRole('heading', { level: 2 })).toHaveText(/^Since you last looked \(([A-Z][a-z]+day|[A-Z][a-z]{2} \d{1,2})\)$/);
  await expect(since).toContainText('Paycheck · Northwind payroll+$4,212');
  await expect(since).toContainText('Utilities · City Power−$486');
  const { head } = (await (await page.request.get('/api/b/ours/spending')).json()) as Head;
  const net = head.money_in_cents - head.money_out_cents;
  const words = head.money_in_cents === 0 && head.money_out_cents === 0 ? 'Nothing in or out yet this month.'
    : net > 0 ? `${dollars(net)} in the black so far this month`
      : net < 0 ? `${dollars(-net)} in the red so far this month` : 'Even so far this month';
  await expect(page.getByTestId('figure')).toHaveText(words);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/\.$/);
});

test('the four signs open Spending, Fixed costs, the Plan and Accounts', async ({ page }) => {
  await page.goto('/');
  await expect(ready(page)).toBeVisible();
  const { month } = (await (await page.request.get('/api/b/ours/home')).json()) as { month: string };
  await expect(page.getByRole('link', { name: /^Flexible spending: / })).toHaveAttribute('href', `/b/ours/spending?month=${month}#flexible`);
  await expect(page.getByRole('link', { name: /^Bills: / })).toHaveAttribute('href', `/b/ours/spending?month=${month}#fixed`);
  await expect(page.getByRole('link', { name: /^Plan: (Comfortably at \d+|Not by 70|No plan yet)$/ })).toHaveAttribute('href', '/b/ours/plan');
  await expect(page.getByRole('link', { name: /^Net worth: \$[\d.,]+[KM]? · / })).toHaveAttribute('href', '/b/ours/accounts');
});

test('For you: the sign-in problems Fix › to Banks, the new-account event folds away, and Dismiss has Undo', async ({ page }) => {
  await page.goto('/');
  const card = page.getByTestId('for-you');
  const row = card.getByRole('listitem').filter({ hasText: SYNC });
  await expect(row.getByRole('link', { name: 'Fix ›' })).toHaveAttribute('href', '/b/ours/settings/banks');
  await expect(card).not.toContainText("New account 'Acct 9999'");
  await expect(card.getByRole('link', { name: /(came in twice|same-account questions)/ })).toHaveAttribute('href', '/b/ours/accounts');
  await row.getByRole('button', { name: `Dismiss: ${SYNC}` }).click();
  await expect(row).toHaveCount(0);
  const toast = page.getByTestId('undo-toast').filter({ hasText: 'Dismissed' });   // in its page's live region
  await expect(toast).toHaveText(/^Dismissed · Undo$/);
  await toast.getByRole('button', { name: 'Undo' }).click();
  await expect(card.getByRole('listitem').filter({ hasText: SYNC })).toBeVisible();
});

test('keeps the day-to-day accounts as today, and All accounts opens the Accounts tab', async ({ page }) => {
  await page.goto('/');
  // Home keeps cash and cards, used day to day (savings and business checking count as cash), by type whatever the
  // source (INS-20), so seed_setasides.py's typed-in House Fund savings is there too; investments, retirement, the
  // 529s, the house and the mortgage are on the Accounts tab.
  for (const g of ['Everyday', 'Savings', 'Cards', 'Business']) await expect(page.getByRole('heading', { name: g, exact: true })).toBeVisible();
  for (const g of ['Investing', 'Retirement', "Kids' savings", 'Home']) await expect(page.getByRole('heading', { name: g, exact: true })).toHaveCount(0);
  const rows = page.locator('[data-testid=account-row]');
  await expect(rows).toHaveCount(7);
  expect((await rows.locator('.acct__name').allTextContents()).sort())
    .toEqual(['Business card', 'Business checking', 'Checking', 'High-yield savings', 'House Fund', 'Rewards Card', 'Savings']);
  await page.getByRole('link', { name: 'All accounts ›' }).click();
  await expect(page).toHaveURL(/\/b\/ours\/accounts$/);
  await expect(page.getByRole('heading', { name: 'Accounts', level: 1 })).toBeVisible();
});

test('the Review tab shows how many are waiting', async ({ page }) => {
  await page.goto('/');
  const review = page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: /Review/ });
  await expect(review.locator('.nav__count')).toHaveText(/^\d+\+?$/);
});

test('the strip opens Spending on this month', async ({ page }) => {
  await page.goto('/');
  const strip = page.getByTestId('flow-strip');
  await expect(strip).toHaveAttribute('href', /^\/b\/ours\/spending\?month=\d{4}-\d{2}$/);
  await strip.click();
  await expect(page).toHaveURL(/\/b\/ours\/spending\?month=\d{4}-\d{2}$/);
  await expect(page.getByRole('navigation', { name: 'Spending views' }).getByRole('link', { name: 'This month' })).toHaveAttribute('aria-current', 'page');
});

// Last in the file: it saves alex's full look, so the Since list above would be empty after it.
test('ten seconds on Home is a look: the next load has nothing new since earlier today', async ({ page }) => {
  await page.clock.install();
  await page.goto('/');
  await expect(ready(page)).toBeVisible();
  const look = page.waitForRequest((r) => r.method() === 'POST' && r.url().endsWith('/home/seen') && r.postDataJSON()?.glance === false);
  await page.clock.fastForward(10_000);
  await (await look).response();
  await page.reload();
  await expect(page.getByTestId('since-nothing')).toHaveText('Nothing new since earlier today.');
});
