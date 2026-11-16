import { expect, test } from '@playwright/test';
import { loginAs, tab, restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

test.beforeEach(async ({ page }) => { await loginAs(page, 'alex'); });

const p = (n: number) => String(n).padStart(2, '0');
const ymd = (d: Date) => `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;

test('search finds a shop and shows plain rows', async ({ page }) => {
  await page.goto('/transactions?dates=all');
  await page.getByLabel('Search').fill('greenleaf');
  await expect(page).toHaveURL(/q=greenleaf/);
  const rows = page.locator('[data-testid=txn-row]');
  await expect(rows.first()).toBeVisible();
  for (const row of (await rows.all()).slice(0, 10)) await expect(row).toContainText(/Greenleaf Market|GREENLEAF MARKET/);
  const amount = rows.first().locator('.money');
  expect(await amount.evaluate((el) => getComputedStyle(el).fontVariantNumeric)).toContain('tabular-nums');
});

test('a category filter applies and shows as a chip', async ({ page }) => {
  await page.goto('/transactions?dates=all');
  await page.getByRole('button', { name: 'Category' }).click();
  await page.getByRole('option', { name: 'Eating out' }).click();
  await expect(page).toHaveURL(/category=dining/);
  await expect(page.getByRole('button', { name: 'Category: Eating out' })).toBeVisible();
  for (const row of (await page.locator('[data-testid=txn-row]').all()).slice(0, 10)) await expect(row).toContainText('Eating out');
});

test('correcting a category in the detail picks from the menu, sticks, and says what it did', async ({ page }, testInfo) => {
  await page.goto('/transactions?dates=all&q=SQ%20*VENDOR');
  const rows = page.locator('[data-testid=txn-row]');
  const row = rows.nth(testInfo.project.name === 'phone' ? 0 : 1);
  await row.click();
  const detail = page.getByTestId('txn-detail');
  await expect(detail).toBeVisible();
  await detail.getByRole('button', { name: /^Category / }).click();
  // Wait for the detail's matching count before touching the box: isVisible() does not wait.
  const counted = page.waitForResponse((r) => /\/transactions\/\d+\/matching$/.test(new URL(r.url()).pathname));
  await page.getByRole('combobox', { name: 'Find a category' }).fill('amazon');
  await page.getByRole('dialog', { name: 'Category' }).getByRole('option', { name: 'Shopping', exact: true }).click();
  const box = detail.getByRole('checkbox', { name: /^Also apply to/ });
  if ((await (await counted).json()).count > 0) await box.uncheck();      // leave the other SQ *VENDOR rows for the Review spec
  await detail.locator('form:not([data-testid=note-form])').getByRole('button', { name: 'Save' }).click();
  await expect(detail.getByText(/^Shopping for (this one only\.|.+\. Steward will remember this for next time\.)$/)).toBeVisible();
  await expect(detail.getByRole('button', { name: 'Undo' })).toBeVisible();
  await page.reload();
  await expect(rows.nth(testInfo.project.name === 'phone' ? 0 : 1)).toContainText('Shopping');
});

test('detail is a sheet on the phone and a pane on the desktop', async ({ page }, testInfo) => {
  await page.goto('/transactions?dates=all');
  await page.locator('[data-testid=txn-row]').first().click();
  const dialog = page.getByRole('dialog');
  if (testInfo.project.name === 'phone') await expect(dialog).toBeVisible();
  else await expect(dialog).toHaveCount(0);
  await expect(page.getByTestId('txn-detail')).toBeVisible();
});

test('more rows load as you reach the end', async ({ page }) => {
  await page.goto('/transactions?dates=all');
  const rows = page.locator('[data-testid=txn-row]');
  await expect(rows).toHaveCount(50);
  await page.getByRole('button', { name: 'Show more' }).scrollIntoViewIfNeeded();
  await page.getByRole('button', { name: 'Show more' }).click();
  await expect(rows).toHaveCount(100);
});

test('the default is the last 7 days and every visible row falls inside it', async ({ page }) => {
  await page.goto('/transactions');
  await expect(page.getByRole('button', { name: 'Dates: Last 7 days' })).toBeVisible();
  const today = new Date();
  const from = ymd(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 6));
  const to = ymd(today);
  const rows = page.locator('[data-testid=txn-row]');
  await expect(rows.first().or(page.getByText('Nothing in the last 7 days.'))).toBeVisible();
  if ((await rows.count()) === 0) {
    await expect(page.getByRole('button', { name: 'Show the last 30 days' })).toBeVisible();
    return;
  }
  const days = await page.locator('[data-date]').evaluateAll((els) => els.map((e) => e.getAttribute('data-date')!));
  expect(days.length).toBeGreaterThan(0);
  for (const d of days) {
    expect(d >= from && d <= to).toBe(true);
  }
});

test('choosing All time from the Dates sheet puts dates=all in the URL', async ({ page }) => {
  await page.goto('/transactions');
  await page.getByRole('button', { name: 'Dates: Last 7 days' }).click();
  const dialog = page.getByRole('dialog', { name: 'Dates' });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('radio', { name: 'All time' }).click();
  await expect(page).toHaveURL(/dates=all/);
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Dates', exact: true })).toBeVisible();
});

test('empty results explain themselves', async ({ page }) => {
  await page.goto('/transactions?dates=custom&from=2020-01-01&to=2020-01-02');
  await expect(page.getByText('Nothing matched.')).toBeVisible();

  await page.goto('/transactions?dates=7&q=zzzznotashop');
  await expect(page.getByText('Nothing in the last 7 days.')).toBeVisible();
  await page.getByRole('button', { name: 'Show the last 30 days' }).click();
  await expect(page).toHaveURL(/dates=30/);
  await expect(page.getByRole('button', { name: 'Dates: Last 30 days' })).toBeVisible();
});

test('a search typed just before a filter pick keeps both in the URL', async ({ page }) => {
  await page.goto('/transactions?dates=all');
  await page.getByLabel('Search').fill('greenleaf');
  await page.getByRole('button', { name: 'Category' }).click();
  await page.getByRole('option', { name: 'Groceries' }).click();
  // The search is debounced: wait until the URL holds both, the real end state, instead of for a time.
  await expect(page).toHaveURL((u) => u.searchParams.get('q') === 'greenleaf' && u.searchParams.get('category') === 'groceries');
});

test('arrow keys in the Dates sheet move without applying; Enter applies', async ({ page }) => {
  await page.goto('/transactions');
  await page.getByRole('button', { name: 'Dates: Last 7 days' }).click();
  const dialog = page.getByRole('dialog', { name: 'Dates' });
  const url = page.url();
  await dialog.getByRole('radio', { name: 'Last 7 days' }).focus();
  await page.keyboard.press('ArrowDown');
  await expect(dialog.getByRole('radio', { name: 'Last 30 days' })).toBeFocused();
  await expect(dialog).toBeVisible();
  expect(page.url()).toBe(url);
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/dates=30/);
  await expect(dialog).toHaveCount(0);
});

test('on the desktop, opening a row moves focus into the pane and closing returns it', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'pane layout only');
  await page.goto('/transactions?dates=all');
  const row = page.locator('[data-testid=txn-row]').first();
  await row.click();
  await expect.poll(() => page.evaluate(() => !!document.activeElement?.closest('[data-testid=txn-detail]'))).toBe(true);
  await page.getByTestId('txn-detail').getByRole('button', { name: 'Close' }).click();
  await expect(row).toBeFocused();
});

test('the pane landmark is absent until a row is open', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'pane layout only');
  await page.goto('/transactions?dates=all');
  await expect(page.getByRole('complementary')).toHaveCount(0);
});

test('the search box follows the URL when it changes elsewhere', async ({ page }) => {
  await page.goto('/transactions?dates=all&q=greenleaf');
  await expect(page.getByLabel('Search')).toHaveValue('greenleaf');
  await tab(page, 'Accounts').click();
  await page.getByRole('link', { name: 'All transactions' }).click();
  await expect(page.getByRole('heading', { name: 'All transactions', exact: true })).toBeVisible();
  await expect(page).not.toHaveURL(/q=/);
  await expect(page.getByLabel('Search')).toHaveValue('');
});

test('the Sorted by filter narrows to what Steward sorted and shows as a chip', async ({ page }) => {
  await page.goto('/transactions?dates=all');
  await page.getByRole('button', { name: 'Sorted by' }).click();
  await page.getByRole('option', { name: 'By Steward, not checked' }).click();
  await expect(page).toHaveURL(/sorted=steward/);
  await expect(page.getByRole('button', { name: 'Sorted by: By Steward, not checked, clear' })).toBeVisible();
});

test('a note is added to a transaction and marked on its row', async ({ page }) => {
  await page.goto('/transactions?dates=all&q=greenleaf');
  const row = page.locator('[data-testid=txn-row]').first();
  await row.click();
  const detail = page.getByTestId('txn-detail');
  const noteForm = detail.getByTestId('note-form');
  await noteForm.getByRole('textbox', { name: 'Note' }).fill('Bought the party food here');
  // The vault is restored, so the "Also…" box is certain to be there, and a note alone leaves it unticked.
  await expect(noteForm.getByLabel(/^Also the /)).not.toBeChecked();
  await noteForm.getByRole('button', { name: 'Save' }).click();
  await expect(detail.getByText(/, .*: Bought the party food here/)).toBeVisible();
  await expect(row.getByText(/\d+ notes?/)).toBeVisible();
});
