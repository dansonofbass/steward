import { expect, test, type Page } from '@playwright/test';
import { loginAs, restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

// Reimbursable expenses end to end on the demo household (seed_reimburse.py): add a trip, mark its likely work, sort
// the repayment in the detail and see the balance fall, then settle the rest. Each project has its own trip, months
// apart, so the two runs never see each other's rows; the payer, Acme, is shared and made on first use.
const PLACE = { phone: { city: 'Denver, CO', word: 'DENVER' }, desktop: { city: 'Austin, TX', word: 'AUSTIN' } } as const;
type Row = { id: number; posted_at: string };

async function owed(page: Page): Promise<number> {
  const s = await (await page.request.get('/api/b/ours/reimburse')).json();
  return (s.payers as { name: string; owed_cents: number }[]).find((p) => p.name === 'Acme')?.owed_cents ?? 0;
}

async function find(page: Page, q: string): Promise<Row> {
  const r = await (await page.request.get(`/api/b/ours/transactions?q=${encodeURIComponent(q)}&limit=50`)).json();
  return (r.transactions as Row[])[0];
}

test('add a trip, mark its likely work, sort the repayment, settle the rest', async ({ page }, info) => {
  test.setTimeout(90_000);
  const p = PLACE[info.project.name as keyof typeof PLACE];
  const town = p.city.split(',')[0];
  await loginAs(page, 'alex');
  await page.request.post('/api/b/ours/reimburse/payers', { data: { name: 'Acme' } });
  const start = (await find(page, `HOTEL TEATRO ${p.word}`)).posted_at;
  const end = (await find(page, `LITTLE PIE SHOP ${p.word}`)).posted_at;
  const before = await owed(page);

  // Add the trip: the city names it, and Save opens its list.
  await page.goto('/spending/reimbursements');
  await page.getByRole('button', { name: 'Add a trip' }).first().click();
  const sheet = page.getByRole('dialog', { name: 'Add a trip' });
  await sheet.getByLabel('Start').fill(start);
  await sheet.getByLabel('End').fill(end);
  await sheet.getByLabel('City (optional)').fill(p.city);
  await expect(sheet.getByLabel('Name')).toHaveValue(`${town} trip`);
  await sheet.getByRole('button', { name: 'Save' }).click();
  await expect(page).toHaveURL(/\/spending\/reimbursements\/trips\/\d+$/);

  // The list: the hotel says the city, the flight was booked ahead, the grocer is home and unticked.
  const rowOf = (raw: string) => page.getByTestId('trip-row').filter({ hasText: raw });
  await expect(page.getByRole('heading', { name: 'Booked before the trip' })).toBeVisible();
  await expect(rowOf(`HOTEL TEATRO ${p.word}`)).toContainText(`says ${town}`);
  await expect(rowOf(`HOTEL TEATRO ${p.word}`).getByRole('checkbox')).toBeChecked();
  await expect(rowOf(`UNITED AIRLINES ${p.word}`)).toContainText('booked ahead');
  const grocer = page.getByRole('region', { name: 'Probably home' }).getByTestId('trip-row').filter({ hasText: 'MAPLE GROCER' }).first();
  await expect(grocer).toContainText('a regular near home');
  await expect(grocer.getByRole('checkbox')).not.toBeChecked();
  await page.getByRole('button', { name: /^Mark \d+ reimbursable · \$[\d,]+\.\d\d$/ }).click();
  await expect(page.getByText(new RegExp(`^${town} trip: \\d+ charges?, \\$[\\d,.]+, reimbursable\\. Acme owes you \\$[\\d,.]+\\.$`))).toBeVisible();
  const marked = await owed(page);
  expect(marked).toBeGreaterThanOrEqual(before + 42_000 + 61_200 + 2_840 + 5_580);

  // The repayment, sorted in the detail: the balance falls by exactly the deposit.
  await page.goto(`/transactions?dates=all&q=${encodeURIComponent(`ACME CORP EXPENSES ${p.word}`)}`);
  await page.getByTestId('txn-row').first().click();
  const detail = page.getByTestId('txn-detail');
  await expect(detail).toBeVisible();
  await detail.getByRole('button', { name: /^Category / }).click();
  await page.getByRole('combobox', { name: 'Find a category' }).fill('per diem');
  await page.getByRole('dialog', { name: 'Category' }).getByRole('option', { name: 'Reimbursement', exact: true }).click();
  await detail.locator('form:not([data-testid=note-form])').getByRole('button', { name: 'Save' }).click();
  await expect(detail.locator('.detail__receipt')).toHaveText(
    /^Reimbursement from Acme\. Acme (now owes you \$[\d,.]+|has paid you \$[\d,.]+ more than you've marked)\.$/);
  expect(await owed(page)).toBe(marked - 105_000);

  // Settle the rest: all square.
  await page.goto('/spending/reimbursements');
  await page.getByTestId('rb-owed').filter({ hasText: 'Acme' }).getByRole('button', { name: 'Settle' }).click();
  const settle = page.getByRole('dialog', { name: 'Settle' });
  await expect(settle).toContainText(/Settle the \$[\d,.]+ Acme still owes you as not coming back\?/);
  await settle.getByRole('button', { name: 'Settle' }).click();
  await expect(page.getByRole('main').getByText('All square with Acme.')).toBeVisible();
  expect(await owed(page)).toBe(0);
});
