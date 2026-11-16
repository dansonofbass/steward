import { expect, test, type Page } from '@playwright/test';
import { daysBack, importFile, loginAs, mdy, restoreVault, serverDay } from './fixtures';

/** A two-row Chase card file dated 3 and 5 days before the e2e server's own day (Engineering choice 16). */
async function chase(page: Page, tag: string) {
  const day = await serverDay(page);
  const [a, b] = [mdy(daysBack(day, 5)), mdy(daysBack(day, 3))];
  return 'Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n'
    + `${a},${a},HARBOR GROCERY ${tag},Groceries,Sale,-64.18,\n${b},${b},CITY PARKING ${tag},Travel,Sale,-12.00,\n`;
}

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });
test.beforeEach(async ({ page }) => { await loginAs(page, 'alex'); });

test('the transactions CSV downloads with no Notes column, and with one when ticked', async ({ page }) => {
  await page.goto('/settings/export');
  const tx = page.getByRole('region', { name: 'Transactions (CSV)' });
  const link = tx.getByRole('link', { name: 'Download' });
  const download = page.waitForEvent('download');
  await link.click();
  expect((await download).suggestedFilename()).toBe('steward-ours-transactions-all.csv');
  const plain = await (await page.request.get((await link.getAttribute('href'))!)).text();
  expect(plain.replace(/^﻿/, '').split('\r\n')[0]).toBe('Date,Account,Description,Name,Category,Amount,Transfer,Business %');
  await tx.getByRole('checkbox', { name: 'Include notes' }).check();
  const noted = await (await page.request.get((await link.getAttribute('href'))!)).text();
  expect(noted.replace(/^﻿/, '').split('\r\n')[0]).toBe('Date,Account,Description,Name,Category,Amount,Transfer,Business %,Notes');
});

test('the encrypted backup downloads a stored ZIP whose export.json names argon2id', async ({ page }) => {
  await page.goto('/settings/export');
  await page.getByRole('button', { name: 'Make one' }).click();
  await page.getByLabel('Passphrase').fill('a long enough passphrase');
  await page.getByLabel('Type it again').fill('a long enough passphrase');
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download backup' }).click();
  expect((await download).suggestedFilename()).toMatch(/^steward-ours-\d{4}-\d{2}-\d{2}\.steward-backup$/);
  // The browser's copy is gone after its one GET; a second backup, fetched here, shows the bytes.
  const made = await (await page.request.post('/api/b/ours/export/backup',
    { data: { passphrase: 'a long enough passphrase', again: 'a long enough passphrase' } })).json();
  const zip = await (await page.request.get(`/api/b/ours/export/backup/${made.token}`)).text();
  expect(zip.startsWith('PK')).toBe(true);
  expect(zip).toContain('"name": "argon2id"');
  expect((await page.request.get(`/api/b/ours/export/backup/${made.token}`)).status()).toBe(404);
});

test('a row says where it came from, and its file opens with that file’s Undo', async ({ page }, info) => {
  const acct = (await (await page.request.post('/api/b/ours/accounts', {
    data: { name: `Came from ${info.project.name}`, type: 'credit', owner: 'joint', balance_cents: 0 } })).json()).id as number;
  await importFile(page, 'ours', acct, 'came-from.csv', await chase(page, 'CAME'));
  await page.goto(`/accounts/${acct}`);
  await page.getByText('HARBOR GROCERY CAME').first().click();
  await expect(page.getByTestId('came-from')).toContainText(/^came-from\.csv · imported \w{3} \d{1,2} by /);
  await page.getByRole('link', { name: 'Show all 2 from this file' }).click();
  await expect(page).toHaveURL(/[?&]batch=\d+/);
  await expect(page.getByText('From came-from.csv')).toBeVisible();
  await page.getByRole('button', { name: 'Undo this import' }).click();
  await page.getByRole('dialog', { name: 'Undo the import of came-from.csv?' }).getByRole('button', { name: 'Undo this import' }).click();
  await expect(page.getByText('Import undone.')).toBeVisible();
  await expect(page.getByText('HARBOR GROCERY CAME')).toHaveCount(0);
});
