import { expect, test, type Page } from '@playwright/test';
import { loginAs, restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

// web/e2e/seed_setasides.py: Big Mutual (yearly), Maple Court HOA (twice a year) and County Tax Collector (one county
// payment, suggested as Property tax) are suggested; a House Fund savings account holds $4,100; Dale's Plumbing was
// paid last month. Each project starts from a restored vault, so the first test (setting Big Mutual aside) runs in both.
// Every other test stands on its own: the only suggestions they look for are the two nobody accepts, and each stops
// what it added.

type Month = { month: string; as_of: string };
const thisMonth = async (page: Page) => (await (await page.request.get('/api/b/ours/spending')).json()) as Month;
/** The calendar day `n` days before an ISO date, as YYYY-MM-DD. */
const daysBack = (iso: string, n: number) => { const [y, m, d] = iso.split('-').map(Number); return new Date(Date.UTC(y, m - 1, d - n)).toISOString().slice(0, 10); };
async function fitsTheScreen(page: Page) {
  const { scroll, inner } = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: window.innerWidth }));
  expect(scroll, 'the page scrolls sideways').toBeLessThanOrEqual(inner);
}
type Row = { id: number; name: string; kind: string };
const listRows = async (page: Page) => ((await (await page.request.get('/api/b/ours/setasides')).json()) as { rows: Row[] }).rows;
async function stopAll(page: Page) {
  for (const r of await listRows(page)) await page.request.delete(`/api/b/ours/setasides/${r.id}`);
}
const views = (page: Page) => page.getByRole('navigation', { name: 'Spending views' });

test.describe('a manager', () => {
  test.beforeEach(async ({ page }) => { await loginAs(page, 'alex'); });
  test.afterEach(async ({ page }) => { await stopAll(page); });

  test("from Spending's tab, tick a suggestion, set it aside, and see it on This month", async ({ page }) => {
    await page.goto('/spending');
    await views(page).getByRole('link', { name: 'Setting aside' }).click();
    await expect(page).toHaveURL(/\/b\/ours\/spending\/setasides$/);
    await expect(page.getByRole('heading', { level: 2, name: 'Yearly costs worth setting aside' })).toBeVisible();
    await expect(page.getByText(/Set all/)).toHaveCount(0);
    const big = page.getByTestId('sa-suggestion').filter({ hasText: 'Big Mutual' });
    await expect(big).toContainText('$1,380 a year');
    await expect(page.getByTestId('sa-suggestion').filter({ hasText: 'Maple Court HOA' })).toContainText('$900 a year');
    await expect(page.getByTestId('sa-suggestion').filter({ hasText: 'Property tax' })).toContainText('$8,420 a year');
    await big.getByRole('checkbox').check();
    await page.getByRole('region', { name: '1 picked · $115 a month' }).getByRole('button', { name: 'Set aside' }).click();
    await expect(page.getByTestId('undo-toast')).toContainText('Set aside 1 · $115 a month');
    const row = page.getByTestId('sa-row').filter({ hasText: 'Big Mutual' });
    await expect(row).toContainText('$115');
    await expect(row).toContainText('No account linked');
    await expect(page.getByTestId('sa-head')).toContainText('$115 a month');
    await expect(page.getByTestId('sa-suggestion')).toHaveCount(2);
    await views(page).getByRole('link', { name: 'This month' }).click();
    await expect(page.getByTestId('sp-line')).toContainText('Set aside $115');
    await expect(page.getByTestId('sa-summary')).toContainText('1 cost');
    const m = await thisMonth(page);
    const paidMonth = daysBack(m.as_of, 15).slice(0, 7);
    if (paidMonth !== m.month) await page.goto(`/spending?month=${paidMonth}`);
    await expect(page.getByTestId('sa-paid-row')).toContainText('Big Mutual');
  });

  test('two picked are set aside in one go, and Undo brings both suggestions back', async ({ page }) => {
    await page.goto('/spending/setasides');
    for (const name of ['Maple Court HOA', 'Property tax']) await page.getByTestId('sa-suggestion').filter({ hasText: name }).getByRole('checkbox').check();
    await page.getByRole('region', { name: /^2 picked · \$[\d,]+ a month$/ }).getByRole('button', { name: 'Set aside' }).click();
    await expect(page.getByTestId('undo-toast')).toContainText(/^Set aside 2 · \$[\d,]+ a month/);
    await expect(page.getByTestId('sa-row')).toHaveCount(2);
    await page.getByTestId('undo-toast').getByRole('button', { name: 'Undo' }).click();
    await expect(page.getByTestId('sa-row')).toHaveCount(0);
    await expect(page.getByTestId('sa-suggestion').filter({ hasText: 'Maple Court HOA' })).toBeVisible();
    await expect(page.getByTestId('sa-suggestion').filter({ hasText: 'Property tax' })).toBeVisible();
  });

  // Nobody accepts these two, so whichever project runs first, both are still offered.
  test('the suggestions nobody has accepted are still offered', async ({ page }) => {
    await page.goto('/spending/setasides');
    await expect(page.getByRole('heading', { level: 2, name: 'Yearly costs worth setting aside' })).toBeVisible();
    await expect(page.getByTestId('sa-suggestion').filter({ hasText: 'Maple Court HOA' })).toBeVisible();
    await expect(page.getByTestId('sa-suggestion').filter({ hasText: 'Property tax' })).toBeVisible();
  });

  test('match a payment by hand from its detail, see it on Spending, and undo it there', async ({ page }) => {
    const m = await thisMonth(page);
    const r = await page.request.post('/api/b/ours/setasides', { data: { name: 'Water heater', kind: 'one_off', amount_cents: 225_000, due_year: Number(m.as_of.slice(0, 4)) + 2, due_month: 12 } });
    expect(r.status()).toBe(201);
    const billMonth = daysBack(m.as_of, 35).slice(0, 7);          // the seed dates the plumber's bill 35 days back
    await page.goto(`/transactions?q=Dale&dates=custom&from=${billMonth}-01&to=${m.as_of}`);
    await page.getByTestId('txn-row').filter({ hasText: "Dale's Plumbing" }).first().click();
    await page.getByRole('button', { name: 'Paid from a set-aside' }).click();
    await page.getByRole('group', { name: 'Which set-aside paid it?' }).getByRole('button', { name: 'Water heater' }).click();
    await expect(page.getByTestId('paid-from')).toContainText('Paid from Setting aside: Water heater');
    await page.goto(`/spending?month=${billMonth}`);
    const paid = page.getByTestId('sa-paid-row').filter({ hasText: 'Water heater' });
    await expect(paid).toContainText("Dale's Plumbing");
    await expect(paid).toContainText('$2,350');
    await expect(page.getByTestId('sp-set-aside-line')).toContainText('paid from Setting aside');
    await paid.getByRole('button', { name: /^Not this one\?/ }).click();
    await expect(page.getByTestId('sa-paid-row').filter({ hasText: 'Water heater' })).toHaveCount(0);
  });

  test('add an estimated one-off and see it on the Plan', async ({ page }) => {
    await page.goto('/spending/setasides/new');
    await page.getByLabel('What is it').fill('Water heater');
    await page.getByRole('radio', { name: 'Once' }).click();
    await page.getByRole('button', { name: 'Water heater', pressed: false }).click();
    await page.getByLabel('Installed in').fill('2014');
    await expect(page.getByTestId('sa-est')).toContainText(/Likely by \d{4} · \$\d+ a month/);
    await fitsTheScreen(page);                                    // the cited sources are long URLs
    await page.getByLabel('Put away in').selectOption({ label: 'House Fund' });
    await page.getByRole('button', { name: 'Set it aside' }).click();
    await expect(page).toHaveURL(/\/spending\/setasides\/\d+$/);
    await expect(page.getByTestId('sa-basis')).toBeVisible();
    await fitsTheScreen(page);
    await expect(page.getByTestId('sa-fund')).toContainText('House Fund');
    await page.goto('/plan');
    await expect(page.getByTestId('big-costs')).toBeVisible();
    const row = page.getByTestId('big-cost-row').filter({ hasText: 'Water heater' });
    await expect(row).toContainText('Estimate');
  });

  test('every Setting aside page fits the screen', async ({ page }) => {
    const r = await page.request.post('/api/b/ours/setasides', { data: { name: 'Home insurance', kind: 'yearly', amount_cents: 138_000, due_month: 5, due_day: 12, payee_key: 'BIG MUTUAL', category: 'insurance' } });
    const id = (await r.json()).id as number;
    for (const [path, ready] of [['/spending/setasides', 'sa-row'], [`/spending/setasides/${id}`, 'sa-fund'], ['/spending/setasides/new', 'sa-form'], ['/spending', 'sa-summary']] as const) {
      await page.goto(path);
      await expect(page.getByTestId(ready).first()).toBeVisible();
      await fitsTheScreen(page);
    }
  });
});

test.describe('a viewer', () => {
  let billMonth = '';
  let hoaKey = '';
  let hoaCategory = '';
  let matchedTxn = 0;
  test.beforeEach(async ({ page }) => {
    await loginAs(page, 'alex');
    const m = await thisMonth(page);
    billMonth = daysBack(m.as_of, 35).slice(0, 7);
    const r = await page.request.post('/api/b/ours/setasides', { data: { name: 'HOA dues', kind: 'twice_yearly', amount_cents: 45_000, due_month: 1, due_day: 15, second_month: 7, second_day: 15 } });
    expect(r.status()).toBe(201);
    const id = (await r.json()).id as number;
    // A matched payment, so a paid row exists on Spending (Dale's bill, matched by hand).
    const t = (await (await page.request.get(`/api/b/ours/transactions?q=Dale&from=${billMonth}-01&to=${m.as_of}`)).json()) as { transactions: { id: number }[] };
    matchedTxn = t.transactions[0].id;
    expect((await page.request.post('/api/b/ours/setasides/match', { data: { transaction_id: t.transactions[0].id, set_aside_id: id } })).ok()).toBeTruthy();
    // A dismissed suggestion, so "Bring it back" would show for a manager.
    const l = (await (await page.request.get('/api/b/ours/setasides')).json()) as { suggestions: { payee_key: string; category: string; name: string }[] };
    const hoa = l.suggestions.find((s) => s.name === 'Maple Court HOA')!;
    hoaKey = hoa.payee_key; hoaCategory = hoa.category;
    expect((await page.request.post('/api/b/ours/setasides/suggestions/dismiss', { data: { payee_key: hoaKey, category: hoaCategory } })).ok()).toBeTruthy();
    await loginAs(page, 'val-viewer', 'pw-viewer-demo-2026');
  });
  test.afterEach(async ({ page }) => {
    await loginAs(page, 'alex');
    await page.request.post('/api/b/ours/setasides/suggestions/restore', { data: { payee_key: hoaKey, category: hoaCategory } });
    await page.request.delete(`/api/b/ours/setasides/match/${matchedTxn}`);   // before stopping: a stopped set-aside's match cannot be undone
    await stopAll(page);
  });

  test('reads the list, a set-aside, Spending and a payment with nothing to change', async ({ page }) => {
    await page.goto('/spending/setasides');
    await expect(page.getByTestId('sa-row').filter({ hasText: 'HOA dues' })).toBeVisible();
    await expect(page.getByTestId('sa-suggestion').filter({ hasText: 'Property tax' })).toBeVisible();
    await expect(page.getByTestId('sa-dismissed').filter({ hasText: 'Maple Court HOA' })).toBeVisible();
    await expect(page.getByRole('link', { name: /Add a set-aside/ })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Set aside' })).toHaveCount(0);
    await expect(page.getByTestId('sa-suggestion').getByRole('checkbox')).toHaveCount(0);
    await expect(page.getByRole('link', { name: /^Change first: / })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^Not / })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^Bring it back: / })).toHaveCount(0);

    await page.goto(`/spending?month=${billMonth}`);
    await expect(page.getByTestId('sa-paid-row').filter({ hasText: 'HOA dues' })).toBeVisible();
    await expect(page.getByRole('button', { name: /^Not this one\?/ })).toHaveCount(0);

    await page.goto(`/transactions?q=Dale&dates=custom&from=${billMonth}-01&to=${(await thisMonth(page)).as_of}`);
    await page.getByTestId('txn-row').filter({ hasText: "Dale's Plumbing" }).first().click();
    await expect(page.getByTestId('paid-from')).toContainText('Paid from Setting aside: HOA dues');
    await expect(page.getByRole('button', { name: 'Not this one' })).toHaveCount(0);
    await page.goto('/transactions?q=Maple&dates=all');
    await page.getByTestId('txn-row').filter({ hasText: /Maple Court HOA/i }).first().click();
    await expect(page.getByTestId('txn-detail')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Paid from a set-aside' })).toHaveCount(0);

    await page.goto('/spending/setasides');
    await page.getByTestId('sa-row').filter({ hasText: 'HOA dues' }).click();
    await expect(page.getByTestId('sa-detail-head')).toContainText('$75 a month');
    await expect(page.getByTestId('sa-payment')).toContainText("Dale's Plumbing");
    await expect(page.getByRole('button', { name: 'Edit' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Stop setting this aside' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^(Link an account|Change the account)$/ })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^Not this one: / })).toHaveCount(0);
    await page.goto('/spending/setasides/new');
    await expect(page).toHaveURL(/\/spending\/setasides$/);
  });
});

