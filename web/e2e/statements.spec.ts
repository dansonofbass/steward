import { expect, test, type Page } from '@playwright/test';
import { bankFiles, loginAs, monthEnd, restoreVault, serverDay, statementPdf, upload } from './fixtures';
import { GATEWAY_PORT } from './ports';

async function account(page: Page, name: string, type: string) {
  const r = await page.request.post('/api/b/ours/accounts', { data: { name, type, owner: 'joint', balance_cents: 0 } });
  return String((await r.json()).id);
}
const calls = async (page: Page) =>
  ((await (await page.request.get(`http://127.0.0.1:${GATEWAY_PORT}/__e2e/statement-calls`)).json()) as { calls: number }).calls;

test.beforeEach(async ({ page }) => {
  await restoreVault();
  await page.request.post(`http://127.0.0.1:${GATEWAY_PORT}/__e2e/reset`);
  await loginAs(page, 'alex');
});

test('statements: a card layout checked once, the next month alone, a gap fixed, imported with joy, undone', async ({ page }, info) => {
  const p = info.project.name;
  const day = await serverDay(page);
  const card = await account(page, `Mom's card ${p}`, 'credit');
  const checking = await account(page, `Mom's checking ${p}`, 'checking');
  await page.goto('/settings/import');
  await page.locator('input[type=file]').setInputFiles([
    await statementPdf(page, 'card-1.pdf', 'chase_card', monthEnd(day, 2)),
    await statementPdf(page, 'checking.pdf', 'chase_checking', monthEnd(day, 1), 'off'),
  ]);
  await page.getByRole('button', { name: 'Check the layout · 1 look' }).click();
  await page.getByLabel('Account for card-1.pdf').selectOption(card);
  await page.getByRole('button', { name: 'Looks right' }).click();
  await expect(page.getByRole('button', { name: 'Off by $12.40 · Check rows' })).toBeVisible();   // checking's retry is done
  const before = await calls(page);
  await page.locator('input[type=file]').setInputFiles([await statementPdf(page, 'card-2.pdf', 'chase_card', monthEnd(day, 1))]);
  await expect(page.getByText(/^Summit Card Services · \w{3} \d{4} · \d+ rows · adds up ✓$/)).toHaveCount(2);
  expect(await calls(page)).toBe(before);                                       // the next month read on the NAS alone
  await page.getByLabel('Account for card-2.pdf').selectOption(card);
  await page.getByLabel('Account for checking.pdf').selectOption(checking);
  await page.getByRole('button', { name: 'Off by $12.40 · Check rows' }).click();
  const amount = page.locator('input[aria-label^="Amount, row"][value="-125.07"]');
  await amount.fill('-112.67');
  await amount.blur();
  await expect(page.locator('.imp-st__gap')).toHaveText('Adds up ✓');
  await page.getByRole('button', { name: 'Done' }).click();
  await expect(page.getByRole('button', { name: 'Preview' })).toBeEnabled();      // enabled again once the account changes have settled
  await page.getByRole('button', { name: 'Preview' }).click();
  await page.getByRole('button', { name: /^Import [\d,]+$/ }).click();
  await expect(page.getByText('3 statements, every one adds up.')).toBeVisible();
  const rows = (await (await page.request.get(`/api/b/ours/transactions?account_id=${card}&limit=500`)).json()).transactions as
    { id: number; raw_description: string; amount_cents: number }[];
  const purchases = rows.filter((t) => !/PAYMENT|RETURN/.test(t.raw_description));
  expect(purchases.length).toBeGreaterThan(0);
  expect(purchases.every((t) => t.amount_cents < 0)).toBe(true);
  const came = (await (await page.request.get(`/api/b/ours/transactions/${purchases[0].id}/came-from`)).json()).came_from;
  expect([came.kind, came.check, came.page]).toEqual(['statement', 'adds_up', 1]);
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(page.getByText('Import undone.')).toBeVisible();
  expect(((await (await page.request.get(`/api/b/ours/transactions?account_id=${card}&limit=500`)).json()).transactions).length).toBe(0);
});

test('row review fits a phone: the page never scrolls sideways, the gap and Undo stay in view', async ({ page }, info) => {
  const day = await serverDay(page);
  const checking = await account(page, `Mom's checking ${info.project.name}`, 'checking');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/settings/import');
  await page.locator('input[type=file]').setInputFiles([await statementPdf(page, 'checking.pdf', 'chase_checking', monthEnd(day, 1), 'off')]);
  await page.getByLabel('Account for checking.pdf').selectOption(checking);
  await page.getByRole('button', { name: 'Off by $12.40 · Check rows' }).click();
  await expect(page.locator('.imp-st__gap')).toContainText('Off by $12.40');
  const fits = () => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
  expect(await fits()).toBe(true);
  const remove = page.getByRole('button', { name: 'Remove row 1', exact: true });
  const box = (await remove.boundingBox())!;
  expect([box.width >= 44, box.height >= 44]).toEqual([true, true]);
  await remove.click();
  await expect(page.getByRole('button', { name: /removed/i })).toBeVisible();
  expect(await fits()).toBe(true);
});

test('a CSV and a statement together, and the line survives leaving the page', async ({ page }) => {
  const day = await serverDay(page);
  await page.goto('/settings/import');
  const csv = bankFiles(day)['amex-basic.csv'];
  await page.locator('input[type=file]').setInputFiles([upload('amex-basic.csv', csv),
    await statementPdf(page, 'boa.pdf', 'boa_checking', monthEnd(day, 1))]);
  await expect(page.getByRole('button', { name: 'Check the layout · 1 look' })).toBeVisible();
  await page.goto('/settings/banks');
  await page.goto('/settings/import');
  await expect(page.getByText('boa.pdf')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Check the layout · 1 look' })).toBeVisible();
});

test('a scanned statement reads page by page on the gateway and imports', async ({ page }, info) => {
  const day = await serverDay(page);
  const end = monthEnd(day, 1);
  const acct = await account(page, `Checking 3456 ${info.project.name}`, 'checking');
  await page.request.post(`http://127.0.0.1:${GATEWAY_PORT}/__e2e/scan-truth`, { data: { sid: 'boa_checking', end } });
  await page.goto('/settings/import');
  await page.locator('input[type=file]').setInputFiles([await statementPdf(page, 'scan_0042.pdf', 'boa_checking', end, 'scan')]);
  await expect(page.getByText(/^Harborview Bank · \w{3} \d{4} · \d+ rows · adds up ✓$/)).toBeVisible();
  await page.getByLabel('Account for scan_0042.pdf').selectOption(acct);
  await page.getByRole('button', { name: 'Preview' }).click();
  await page.getByRole('button', { name: /^Import [\d,]+$/ }).click();
  await expect(page.getByText(/^Imported [\d,]+ into /)).toBeVisible();
});

test('a scan read with a slipped digit opens row review with its descriptions marked', async ({ page }, info) => {
  const day = await serverDay(page);
  const end = monthEnd(day, 1);
  const acct = await account(page, `Checking 7788 ${info.project.name}`, 'checking');
  await page.request.post(`http://127.0.0.1:${GATEWAY_PORT}/__e2e/scan-truth`, { data: { sid: 'boa_checking', end, slip: 900 } });
  await page.goto('/settings/import');
  await page.locator('input[type=file]').setInputFiles([await statementPdf(page, 'scan_slip.pdf', 'boa_checking', end, 'scan')]);
  await page.getByLabel('Account for scan_slip.pdf').selectOption(acct);
  await page.getByRole('button', { name: 'Off by $9.00 · Check rows' }).click();
  await expect(page.getByText('Descriptions read from a scan · check them')).toBeVisible();
});

test('closing the page mid-scan: reopening Import shows the scan still reading or done', async ({ page }) => {
  const day = await serverDay(page);
  const end = monthEnd(day, 1);
  await page.request.post(`http://127.0.0.1:${GATEWAY_PORT}/__e2e/scan-truth`, { data: { sid: 'boa_checking', end } });
  await page.goto('/settings/import');
  await page.locator('input[type=file]').setInputFiles([await statementPdf(page, 'scan_away.pdf', 'boa_checking', end, 'scan')]);
  await expect(page.getByText('scan_away.pdf')).toBeVisible();
  await page.goto('/settings/banks');
  await page.goto('/settings/import');
  await expect(page.getByText('scan_away.pdf')).toBeVisible();
  await expect(page.getByText(/^(Harborview Bank · \w{3} \d{4} · \d+ rows · adds up ✓|Choose its account to check it|Scanned · reading on Zebra-Box.*|Waiting to be read)$/)).toBeVisible();
});

test('a parent book stages and imports a statement too', async ({ page }, info) => {
  const slug = `margaret-ellis-seed-${info.project.name}`;
  const day = await serverDay(page);
  // An account SimpleFIN doesn't feed, so there is nothing to skip against (as import.spec's parent-book test does).
  const accts = (await (await page.request.get(`/api/b/${slug}/accounts`)).json()).accounts as { id: number; type: string; source: string; is_active: boolean }[];
  const target = accts.find((a) => a.is_active && a.source !== 'simplefin' && ['checking', 'savings'].includes(a.type));
  expect(target).toBeTruthy();
  await page.goto(`/b/${slug}/settings/import`);
  await page.locator('input[type=file]').setInputFiles([await statementPdf(page, 'boa.pdf', 'boa_checking', monthEnd(day, 1))]);
  await page.getByLabel('Account for boa.pdf').selectOption(String(target!.id));
  await page.getByRole('button', { name: 'Check the layout · 1 look' }).click();
  await page.getByRole('button', { name: 'Looks right' }).click();
  await expect(page.getByRole('button', { name: 'Preview' })).toBeEnabled();      // enabled again once the account changes have settled
  await page.getByRole('button', { name: 'Preview' }).click();
  await page.getByRole('button', { name: /^Import [\d,]+$/ }).click();
  await expect(page.getByText(/^Imported [\d,]+ into /)).toBeVisible();
});

test('a parent book: an IRA statement brings its holdings, and Inventory shows them', async ({ page }, info) => {
  const slug = `margaret-ellis-seed-${info.project.name}`;
  const day = await serverDay(page);
  const end = monthEnd(day, 1);
  // Any account the seed already keeps in Inventory: holdings show on its item whatever its type.
  const items = (await (await page.request.get(`/api/b/${slug}/inventory`)).json()).items as
    { id: number; kind: string; account_id: number | null }[];
  const item = items.find((i) => i.kind === 'account' && i.account_id !== null)!;
  await page.goto(`/b/${slug}/settings/import`);
  await page.locator('input[type=file]').setInputFiles([await statementPdf(page, 'IRA_Q1.pdf', 'vanguard_ira', end)]);
  await page.getByLabel('Account for IRA_Q1.pdf').selectOption(String(item.account_id));
  await page.getByRole('button', { name: 'Check the holdings · 1 look' }).click();
  await expect(page.getByText('Holdings add up to the total ✓')).toBeVisible();
  await page.getByRole('button', { name: 'Looks right' }).click();
  await page.getByRole('button', { name: 'Preview' }).click();
  await expect(page.getByText('Holdings 1 statement')).toBeVisible();
  await page.getByRole('button', { name: /^Import [\d,]+$/ }).click();
  await expect(page.getByText(/^Imported [\d,]+ into /)).toBeVisible();
  await page.goto(`/b/${slug}/inventory/${item.id}`);
  await expect(page.getByRole('heading', { name: /^Holdings on \w{3} \d{1,2}, \d{4}$/ })).toBeVisible();
});

test('in gateway mode the gateway opens every PDF: a statement and a scan go through its extract and render', async ({ page }) => {
  const day = await serverDay(page);
  const end = monthEnd(day, 1);
  const pdfCalls = async () =>
    (await (await page.request.get(`http://127.0.0.1:${GATEWAY_PORT}/__e2e/pdf-calls`)).json()) as { extract: number; render: number };
  await page.request.post(`http://127.0.0.1:${GATEWAY_PORT}/__e2e/scan-truth`, { data: { sid: 'boa_checking', end } });
  await page.goto('/settings/import');
  await page.locator('input[type=file]').setInputFiles([
    await statementPdf(page, 'card-remote.pdf', 'chase_card', end),
    await statementPdf(page, 'scan-remote.pdf', 'boa_checking', end, 'scan'),
  ]);
  await expect(page.getByRole('button', { name: 'Check the layout · 1 look' })).toBeVisible();
  await expect(page.getByText(/^(Harborview Bank · \w{3} \d{4} · \d+ rows · adds up ✓|Choose its account to check it)$/)).toBeVisible();
  const calls = await pdfCalls();
  expect(calls.extract).toBe(2);
  expect(calls.render).toBeGreaterThanOrEqual(1);
  await page.goto('/b/ours/settings/chat');
  await expect(page.getByText('PDFs are read on Zebra-Box')).toBeVisible();
});
