import { expect, test, type Page } from '@playwright/test';
import { loginAs, logout, tab, restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

// The e2e tsconfig carries no node types.
declare const Buffer: { from(s: string): never; alloc(n: number, fill: number): never; concat(parts: never[]): never };

// The synthetic parent, seeded per project by seed_extra.py, so phone and desktop never share writes.
const seeded = (project: string) => `margaret-ellis-seed-${project}`;
// Screenshots for JR's check (not committed): the phone project is 390 px wide, the desktop one 1280 px.
async function shot(page: Page, project: string, name: string) {
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: `e2e/screenshots-inventory/${project}-${name}.png`, fullPage: true });
}
const NO_GENDER = /\b(her|hers|she)\b/i;

test.describe.serial('inventory', () => {
  // Light theme for the screenshots; the sky theme would follow the clock.
  test.beforeEach(async ({ page }) => { await page.addInitScript(() => localStorage.setItem('steward-theme', 'light')); });

  test('Home reads like the mockup', async ({ page }, info) => {
    const slug = seeded(info.project.name);
    await loginAs(page, 'alex');
    await page.goto(`/b/${slug}`);
    await expect(page.getByText('Net worth, known items')).toBeVisible();
    await expect(page.getByText('Needs checking: 2')).toBeVisible();
    await expect(page.getByText("Is this one of Margaret's?").first()).toBeVisible();
    await expect(tab(page, 'Inventory')).toBeVisible();
    expect(await page.locator('main').innerText()).not.toMatch(NO_GENDER);
    await shot(page, info.project.name, 'home');
  });

  test('the list filters, and an item shows its full number on Show', async ({ page }, info) => {
    const slug = seeded(info.project.name);
    await loginAs(page, 'alex');
    await page.goto(`/b/${slug}/inventory`);
    await expect(page.getByTestId('item-row')).toHaveCount(18);
    // All transactions comes first, before the groups; insurance is listed as Policies.
    const all = page.getByRole('main').getByRole('link', { name: 'All transactions' });
    await expect(all).toBeVisible();
    const firstRow = await page.getByTestId('item-row').first().elementHandle();
    expect(await all.evaluate((a, row) => !!(a.compareDocumentPosition(row!) & Node.DOCUMENT_POSITION_FOLLOWING), firstRow)).toBe(true);
    await expect(page.getByRole('region', { name: 'Policies' }).getByTestId('item-row').filter({ hasText: 'Long-term care' })).toBeVisible();
    expect(await page.locator('main').innerText()).not.toMatch(NO_GENDER);
    await shot(page, info.project.name, 'list');
    await page.getByRole('group', { name: 'Status' }).getByRole('button', { name: /Needs checking/ }).click();
    await expect(page.getByTestId('item-row')).toHaveCount(2);
    await page.getByTestId('item-row').filter({ hasText: 'Long-term care' }).click();
    await expect(page.getByRole('heading', { name: 'Long-term care' })).toBeVisible();
    await shot(page, info.project.name, 'item-insurance');
    await page.getByRole('button', { name: 'Show' }).click();
    await expect(page.getByText('EM-LTC-0047730')).toBeVisible();
    await page.goto(`/b/${slug}/settings/changes`);
    await expect(page.getByText(/showed the full number/).first()).toBeVisible();
    expect(await page.locator('main').innerText()).not.toMatch(NO_GENDER);
    await shot(page, info.project.name, 'changes');
  });

  test("Inventory's All transactions lists the book's transactions, with a way back to Inventory", async ({ page }, info) => {
    const slug = seeded(info.project.name);
    await loginAs(page, 'alex');
    await page.goto(`/b/${slug}/inventory`);
    await page.getByRole('main').getByRole('link', { name: 'All transactions' }).click();
    await expect(page).toHaveURL(new RegExp(`/b/${slug}/transactions\\?dates=all$`));
    await expect(page.getByRole('heading', { name: 'All transactions', level: 1 })).toBeVisible();
    await page.getByRole('main').getByRole('link', { name: 'Inventory', exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/b/${slug}/inventory$`));
  });

  test('the account and document item pages', async ({ page }, info) => {
    const slug = seeded(info.project.name);
    await loginAs(page, 'alex');
    await page.goto(`/b/${slug}/inventory`);
    await page.getByTestId('item-row').filter({ hasText: 'Joint checking' }).click();
    await expect(page.getByRole('heading', { name: 'Joint checking' })).toBeVisible();
    await shot(page, info.project.name, 'item-account');
    await page.goBack();
    await page.getByTestId('item-row').filter({ hasText: 'Durable power of attorney' }).click();
    await expect(page.getByRole('heading', { name: 'Durable power of attorney' })).toBeVisible();
    await shot(page, info.project.name, 'item-document');
  });

  test('a file over 25 MB is refused with the plain reason and leaves no file', async ({ page }, info) => {
    const slug = seeded(info.project.name);
    await loginAs(page, 'alex');
    await page.goto(`/b/${slug}/inventory`);
    await page.getByTestId('item-row').filter({ hasText: 'Homeowners' }).click();
    const id = Number(page.url().split('/').pop());
    await page.getByRole('link', { name: 'Attach a file' }).first().click();
    const big = Buffer.concat([Buffer.from('%PDF-1.4\n'), Buffer.alloc(26 * 1024 * 1024, 0x20)]);
    await page.getByLabel('Choose a file').setInputFiles({ name: 'Homeowners policy.pdf', mimeType: 'application/pdf', buffer: big });
    await expect(page.getByText(/Not attached: it's over 25 MB/)).toBeVisible();
    const item = await page.request.get(`/api/b/${slug}/inventory/items/${id}`);
    expect(item.ok()).toBeTruthy();
    expect((await item.json()).files).toHaveLength(0);
    // the real server refuses it the same way when the browser doesn't stop it first
    const direct = await page.request.post(`/api/b/${slug}/inventory/files`, {
      multipart: { item_id: String(id), file: { name: 'big.pdf', mimeType: 'application/pdf', buffer: big } } });
    expect(direct.status()).toBe(413);
    expect((await direct.json()).error).toMatch(/over 25 MB/);
    expect((await (await page.request.get(`/api/b/${slug}/inventory/items/${id}`)).json()).files).toHaveLength(0);
  });

  test('attaching a statement confirms the annuity', async ({ page }, info) => {
    const slug = seeded(info.project.name);
    await loginAs(page, 'alex');
    await page.goto(`/b/${slug}/inventory`);
    await page.getByTestId('item-row').filter({ hasText: 'Deferred annuity' }).click();
    await page.getByRole('link', { name: 'Attach a file' }).first().click();
    await expect(page.getByRole('checkbox', { name: /Mark Deferred annuity Confirmed/ })).toBeChecked();
    await page.getByLabel('Choose a file').setInputFiles({ name: 'Westmark annual statement 2025.pdf', mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4\n%made-up statement\n%%EOF\n') });
    await expect(page.getByText(/Attached · PDF/)).toBeVisible();
    await page.getByLabel('Choose a file').setInputFiles({ name: 'Westmark export.xlsx', mimeType: 'application/octet-stream', buffer: Buffer.from('PK') });
    await expect(page.getByText(/Not attached: Steward takes PDF, PNG, JPEG, HEIC or CSV/)).toBeVisible();
    await shot(page, info.project.name, 'attach');
    await page.getByRole('button', { name: 'Done' }).click();
    await expect(page.getByText('Confirmed').first()).toBeVisible();
    const download = page.waitForEvent('download');
    await page.getByRole('link', { name: /Download Westmark annual statement 2025\.pdf/ }).click();
    expect((await download).suggestedFilename()).toBe('Westmark annual statement 2025.pdf');
  });

  test("suggestions: Not Margaret's and Add", async ({ page }, info) => {
    const slug = seeded(info.project.name);
    await loginAs(page, 'alex');
    await page.goto(`/b/${slug}/inventory/suggestions`);
    await expect(page.getByRole('article')).toHaveCount(3);
    expect(await page.locator('main').innerText()).not.toMatch(NO_GENDER);
    await shot(page, info.project.name, 'suggestions');
    await page.getByRole('article', { name: /Harbor Savings Bank/ }).getByRole('button', { name: "Not Margaret's" }).click();
    await expect(page.getByText("Not Margaret's: Harbor Savings Bank")).toBeVisible();
    await page.getByRole('article', { name: /Globe Mutual/ }).getByRole('link', { name: 'Add as insurance' }).click();
    await expect(page.getByText('Filled in from 4 Globe Mutual payments')).toBeVisible();
    await shot(page, info.project.name, 'item-form');
    await page.getByRole('button', { name: 'Add item' }).click();
    await expect(page).toHaveURL(/\/inventory\/\d+$/);
    await expect(page.getByRole('heading', { name: 'Medicare supplement' })).toBeVisible();
  });

  test('a tax form joins or starts a suggestion', async ({ page }, info) => {
    const slug = seeded(info.project.name);
    await loginAs(page, 'alex');
    await page.goto(`/b/${slug}/inventory/tax-form`);
    await page.getByRole('radio', { name: '1099-R' }).check({ force: true });
    await page.getByLabel("Payer's name").fill('Lakeside Teachers Pension');
    await page.getByLabel('Box 1 Gross distribution').fill('12000');
    await page.getByLabel('Box 7 Distribution code').fill('7');
    await page.getByRole('button', { name: "Save and check Margaret's items" }).click();
    await expect(page.getByText(/1099-R saved/)).toBeVisible();
    expect(await page.locator('main').innerText()).not.toMatch(NO_GENDER);
    await shot(page, info.project.name, 'tax-form');
  });

  test('a viewer sees everything except suggestions and changes nothing', async ({ page }, info) => {
    const slug = seeded(info.project.name);
    await loginAs(page, `vee-${info.project.name}`, 'pw-viewer-demo-2026');
    await page.goto(`/b/${slug}`);
    await expect(page.getByText(/Needs checking:/)).toBeVisible();
    await expect(page.getByText(/Is this one of/)).toHaveCount(0);
    await page.goto(`/b/${slug}/inventory`);
    await expect(page.getByText('You can see this book but not change it.')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Add an item' })).toHaveCount(0);
    await shot(page, info.project.name, 'viewer-list');
    await page.getByTestId('item-row').filter({ hasText: 'Joint checking' }).click();
    await expect(page.getByRole('link', { name: 'Edit' })).toHaveCount(0);
    await shot(page, info.project.name, 'viewer-item');
    const r = await page.request.post(`/api/b/${slug}/inventory/items`, { data: { kind: 'contact', name: 'x', owner: 'margaret', details: { role: 'other' } } });
    expect(r.status()).toBe(403);
    const s = await page.request.get(`/api/b/${slug}/inventory/suggestions`);
    expect(s.status()).toBe(404);
    await logout(page);
  });
});
