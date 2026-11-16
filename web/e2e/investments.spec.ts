import { expect, test, type Page } from '@playwright/test';
import { loginAs, tab, restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

const CSV = 'e2e/fixtures/positions.csv';   // relative to web/, where Playwright runs (as onboarding.spec.ts does)
const amount = (t: string) => (t.includes('−') ? -1 : 1) * Number(t.replace(/[^\d.]/g, ''));

test.beforeEach(async ({ page }) => { await loginAs(page, 'alex'); });

async function open(page: Page, name: RegExp) {
  await page.goto('/');
  await tab(page, 'Accounts').click();
  await page.getByRole('region', { name: 'Investments' }).getByRole('link', { name }).click();
}

test("the demo's Taxable page says what the bank sends, how this year went and what it holds, from its own chunk", async ({ page }) => {
  const chunks: string[] = [];
  page.on('request', (r) => { if (/\/Investment-[\w-]+\.js$/.test(r.url())) chunks.push(r.url()); });
  await open(page, /^Taxable/);
  await expect(page.getByRole('heading', { name: 'Taxable', level: 1 })).toBeVisible();
  const inv = page.getByTestId('investment');
  await expect(inv.getByText(/^Robo Invest sends: balance, (no )?transactions, (no )?holdings$/)).toBeVisible();
  await expect(inv.getByText(/^(This year|No balance from this year yet\.)$/).first()).toBeVisible();
  await expect(inv.getByRole('img', { name: /^Balance from / })).toBeVisible();
  await expect(inv.getByText(/^Since .+ \(when Steward started watching\)$/)).toBeVisible();
  await expect(inv.getByRole('heading', { name: "What it's invested in" })).toBeVisible();
  await expect(inv.getByText(/^US stocks \d+%$/)).toBeVisible();
  expect(chunks.length).toBeGreaterThan(0);
});

test("the demo's 401(k) has its contributions against the limit, and a fund's unknown cost can be added", async ({ page }) => {
  await open(page, /^401\(k\)/);
  const inv = page.getByTestId('investment');
  await expect(inv.getByRole('heading', { name: 'Contributions this year' })).toBeVisible();
  await expect(inv.getByText(/(On pace for \$[\d,]+ by Dec 31: \$[\d,]+ short of the limit\.|On pace to max it by Dec 31\.|Maxed for \d{4}\.|This year's limits aren't in Steward yet\.)/)).toBeVisible();
  const row = inv.getByRole('row', { name: /ACMEX/ });
  await expect(row).toBeVisible();
  const add = row.getByRole('button', { name: 'Add' });
  if (await add.isVisible()) {
    await expect(row).toContainText('cost unknown · Add');
    await add.click();
    await row.getByLabel('Expense ratio for ACMEX (% a year)').fill('0.45');
    await row.getByRole('button', { name: 'Save' }).click();
  }
  await expect(row.locator('td').last()).toHaveText(/^\$[\d,]+$/);
});

test('a positions CSV imports into Taxable: the columns, the total against the balance, then the mix and costs', async ({ page }) => {
  await open(page, /^Taxable/);
  const inv = page.getByTestId('investment');
  await inv.getByRole('button', { name: 'Import positions' }).click();
  const sheet = page.getByRole('dialog', { name: 'Import positions' });
  await sheet.getByLabel('Positions file (CSV)').setInputFiles(CSV);
  const preview = sheet.getByRole('button', { name: 'Preview' });
  const line = sheet.getByTestId('positions-preview');
  await expect(preview.or(line)).toBeVisible();
  if (await preview.isVisible()) {          // the first import from Robo Invest asks; the next one remembers
    await expect(sheet.getByLabel('Value')).toHaveValue('Market Value');
    await preview.click();
  }
  await expect(line).toHaveText(/^3 positions · \$180,000; your balance is \$[\d,]+/);
  await sheet.getByRole('button', { name: 'Save' }).click();
  await expect(sheet).toHaveCount(0);
  for (const symbol of ['VTI', 'VXUS', 'BND']) await expect(inv.getByRole('row', { name: new RegExp(symbol) })).toBeVisible();
  await expect(inv.getByText(/^from positions\.csv's import, /)).toBeVisible();
  await expect(inv.getByText(/^(US stocks|International|Bonds) \d+%$/).first()).toBeVisible();
});

test('the net worth split on Accounts adds up to net worth', async ({ page }) => {
  await page.goto('/accounts');
  const split = page.getByRole('region', { name: 'Net worth' });
  await expect(split.getByTestId('nws-total')).toBeVisible();
  const total = amount(await split.getByTestId('nws-total').innerText());
  const lines = await split.getByTestId('nws-line').allInnerTexts();
  expect(lines.length).toBeGreaterThanOrEqual(3);
  expect(Math.round(lines.map(amount).reduce((s, n) => s + n, 0) * 100)).toBe(Math.round(total * 100));
  await split.getByText('Investable', { exact: true }).click();
  await expect(split.getByRole('link', { name: /^Taxable$/ })).toBeVisible();
});
