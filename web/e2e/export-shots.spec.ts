import { test, type Page } from '@playwright/test';
import { daysBack, importFile, loginAs, mdy, restoreVault, serverDay } from './fixtures';
import { DEMO_PORT } from './ports';

declare const process: { env: Record<string, string | undefined> };
const TASK = process.env.SHOTS_TASK;
const SIZES = [['1280x800', { width: 1280, height: 800 }], ['390x844', { width: 390, height: 844 }]] as const;
const OUT = `../.superpowers/sdd/2026-10-31-steward-import-2/shots/task-${TASK}`;
const BY_TASK: Record<string, string[]> = { '6': ['export', 'backup'], '7': ['came-from', 'batch'] };
/** Two rows dated 5 and 3 days before the e2e server's own day (Engineering choice 16). */
async function chase(page: Page) {
  const day = await serverDay(page);
  const [a, b] = [mdy(daysBack(day, 5)), mdy(daysBack(day, 3))];
  return 'Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n'
    + `${a},${a},HARBOR GROCERY,Groceries,Sale,-64.18,\n${b},${b},CITY PARKING,Travel,Sale,-12.00,\n`;
}

let shot = 0;
async function state(page: Page, name: string) {
  if (name === 'export' || name === 'backup') {
    await page.goto('/settings/export');
    await page.getByRole('heading', { name: 'Export', level: 2 }).waitFor();
    if (name === 'backup') {
      await page.getByRole('button', { name: 'Make one' }).click();
      await page.getByLabel('Passphrase').fill('short');
      await page.getByRole('button', { name: 'Download backup' }).click();
      await page.getByText('Use at least 12 characters.').waitFor();
    }
    return;
  }
  shot += 1;
  const acct = (await (await page.request.post('/api/b/ours/accounts', {
    data: { name: `Shots ${shot}`, type: 'credit', owner: 'joint', balance_cents: 0 } })).json()).id as number;
  await importFile(page, 'ours', acct, 'chase-card-shots.csv', await chase(page));
  const groups = (await (await page.request.get('/api/b/ours/import/batches')).json()).imports as { files: { id: number }[] }[];
  const bid = groups[0].files[0].id;
  await page.goto(`/transactions?batch=${bid}&dates=all`);
  await page.getByText('From chase-card-shots.csv').waitFor();
  if (name === 'came-from') {
    await page.getByText('HARBOR GROCERY').first().click();
    await page.getByText(/^chase-card-shots\.csv · imported /).waitFor();
  }
}

test.describe('Export and Came from screenshots (the gate for Tasks 6 and 7)', () => {
  test.skip(!TASK || !BY_TASK[TASK], 'set SHOTS_TASK to 6 or 7');
  test('each state at both sizes, light and dark', async ({ browser }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'one run is enough');
    test.setTimeout(600_000);
    for (const name of BY_TASK[TASK!]) {
      for (const theme of ['light', 'dark'] as const) {
        for (const [size, viewport] of SIZES) {
          await restoreVault();
          const ctx = await browser.newContext({ viewport, baseURL: `http://localhost:${DEMO_PORT}` });
          await ctx.addInitScript((t) => { localStorage.setItem('steward-theme', t); }, theme);
          const page = await ctx.newPage();
          await loginAs(page, 'alex');
          await state(page, name);
          await page.evaluate(() => Promise.all([document.fonts.ready, ...document.getAnimations().map((a) => a.finished.catch(() => null))]));
          await page.screenshot({ path: `${OUT}/${name}-${size}-${theme}.png` });
          await ctx.close();
        }
      }
    }
  });
});
