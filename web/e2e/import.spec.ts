import { expect, test, type Page } from '@playwright/test';
import { bankFiles, loginAs, restoreVault, serverDay, upload } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });
test.beforeEach(async ({ page }) => { await loginAs(page, 'alex'); });

/** The bank files, every date counted back from the server's own day (Engineering choice 23). */
async function files(page: Page, ...names: ('amex-basic.csv' | 'bank.ofx' | 'first-cu.csv')[]) {
  const built = bankFiles(await serverDay(page));
  return names.map((n) => upload(n, built[n]));
}
async function account(page: Page, slug: string, name: string, type: string) {
  const r = await page.request.post(`/api/b/${slug}/accounts`, { data: { name, type, owner: 'joint', balance_cents: 0 } });
  return (await r.json()).id as number;
}
async function rows(page: Page, accountId: number) {
  return (await (await page.request.get(`/api/b/ours/transactions?account_id=${accountId}&limit=500`)).json()).transactions as
    { raw_description: string; amount_cents: number }[];
}

test('three banks in one batch: confirm, preview, import, Undo, and the layout remembered', async ({ page }, info) => {
  const p = info.project.name;
  const card = await account(page, 'ours', `Amex ${p}`, 'credit');
  const checking = await account(page, 'ours', `First CU ${p}`, 'checking');
  const savings = await account(page, 'ours', `Savings ${p}`, 'savings');
  await page.goto('/settings/import');
  await page.locator('input[type=file]').setInputFiles(await files(page, 'amex-basic.csv', 'bank.ofx', 'first-cu.csv'));
  await expect(page.getByText('OFX · 3 rows')).toBeVisible();
  await page.getByLabel('Account for amex-basic.csv').selectOption(String(card));
  await page.getByLabel('Account for first-cu.csv').selectOption(String(checking));
  await page.getByLabel('Account for bank.ofx').selectOption(String(savings));
  await expect(page.getByText('New layout · check the columns')).toHaveCount(2);
  await expect(page.getByRole('radio', { name: 'Purchases are positive' })).toBeChecked();   // clear by payment words
  const use = page.getByRole('button', { name: 'Use this layout' });
  await use.first().click();
  await expect(use).toHaveCount(1);                       // collapse() animates; wait for the fold before the next
  await use.first().click();
  await page.getByRole('button', { name: 'Preview' }).click();
  const pv = page.locator('dl.imp-pv');
  await expect(pv.locator('div').first()).toHaveText('New transactions16');
  await page.getByRole('button', { name: 'Import 16' }).click();
  await expect(page.getByText('Imported 16 into 3 accounts')).toBeVisible();
  const amex = await rows(page, card);
  expect(amex.filter((t) => t.raw_description !== 'AUTOPAY PAYMENT - THANK YOU').every((t) => t.amount_cents < 0)).toBe(true);
  const past = page.getByRole('region', { name: 'Past imports' });
  await past.getByRole('button', { name: 'Undo this import' }).first().click();
  await page.getByRole('dialog', { name: 'Undo the import of 3 files?' }).getByRole('button', { name: 'Undo this import' }).click();
  await expect(past.getByText(/^Undone /).first()).toBeVisible();
  expect(await rows(page, card)).toHaveLength(0);
  await page.locator('input[type=file]').setInputFiles(await files(page, 'first-cu.csv'));
  await expect(page.getByText(`First CU ${p} · remembered layout`)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Use this layout' })).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Remembered layouts' }).getByText(new RegExp(`^First CU ${p} · last used`))).toBeVisible();
});

test('a parent book imports into its own account and records it', async ({ page }, info) => {
  const slug = `margaret-ellis-seed-${info.project.name}`;
  // A parent book makes accounts through its inventory, so take one that SimpleFIN doesn't feed (nothing to skip against).
  const accts = (await (await page.request.get(`/api/b/${slug}/accounts`)).json()).accounts as { id: number; type: string; source: string; is_active: boolean }[];
  const target = accts.find((a) => a.is_active && a.source !== 'simplefin' && ['checking', 'savings'].includes(a.type));
  expect(target).toBeTruthy();
  await page.goto(`/b/${slug}/settings/import`);
  await page.locator('input[type=file]').setInputFiles(await files(page, 'first-cu.csv'));
  await page.getByLabel('Account for first-cu.csv').selectOption(String(target!.id));
  await page.getByRole('button', { name: 'Use this layout' }).click();
  await page.getByRole('button', { name: 'Preview' }).click();
  await page.getByRole('button', { name: /^Import [\d,]+$/ }).click();
  await expect(page.getByText(/^Imported [\d,]+ into /)).toBeVisible();
  await page.goto(`/b/${slug}/settings/changes`);
  await expect(page.getByText('imported first-cu.csv').first()).toBeVisible();
});
