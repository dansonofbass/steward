import { expect, test, type Page } from '@playwright/test';
import { bankFiles, loginAs, restoreVault, serverDay, upload } from './fixtures';
import { DEMO_PORT } from './ports';

declare const process: { env: Record<string, string | undefined> };
const TASK = process.env.SHOTS_TASK;
const SIZES = [['1280x800', { width: 1280, height: 800 }], ['390x844', { width: 390, height: 844 }]] as const;
// Playwright runs from web/ and creates the folder when it saves.
const OUT = `../.superpowers/sdd/2026-10-31-steward-import-1/shots/task-${TASK}`;
const BY_TASK: Record<string, string[]> = { '9': ['files', 'preview', 'done'], '10': ['files', 'preview', 'done', 'layouts'] };

async function account(page: Page, name: string, type: string) {
  const r = await page.request.post('/api/b/ours/accounts', { data: { name, type, owner: 'joint', balance_cents: 0 } });
  return String((await r.json()).id);
}

/** The states the gate shoots, each built on the one before. */
async function files(page: Page, tag: string) {
  const card = await account(page, `Shots card ${tag}`, 'credit');
  const checking = await account(page, `Shots checking ${tag}`, 'checking');
  const built = bankFiles(await serverDay(page));
  await page.goto('/settings/import');
  await page.locator('input[type=file]').setInputFiles((['amex-basic.csv', 'bank.ofx', 'first-cu.csv'] as const).map((n) => upload(n, built[n])));
  await page.getByText('OFX · 3 rows').waitFor();
  await page.getByLabel('Account for amex-basic.csv').selectOption(card);
  await page.getByLabel('Account for first-cu.csv').selectOption(checking);
  await page.getByLabel('Account for bank.ofx').selectOption(checking);
}
async function toPreview(page: Page) {
  const use = page.getByRole('button', { name: 'Use this layout' });
  for (let n = await use.count(); n > 0; n = await use.count()) {
    await use.first().click();
    await expect(use).toHaveCount(n - 1);   // collapse() animates; wait for the fold before the next
  }
  await page.getByRole('button', { name: 'Preview' }).click();
  await page.getByText('New transactions').waitFor();
}
async function toDone(page: Page) {
  await page.getByRole('button', { name: /^Import [\d,]+$/ }).click();
  await page.getByText(/^Imported [\d,]+ into/).waitFor();
}
async function settle(page: Page) {
  await page.evaluate(() => Promise.all([document.fonts.ready, ...document.getAnimations().map((a) => a.finished.catch(() => null))]));
}

test.describe('Import screenshots (the gate for Tasks 9 and 10)', () => {
  test.skip(!TASK || !BY_TASK[TASK], 'set SHOTS_TASK to 9 or 10');
  test('Settings › Import in each state at both sizes, light and dark', async ({ browser }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'one run is enough');
    test.setTimeout(600_000);
    for (const state of BY_TASK[TASK!]) {
      for (const theme of ['light', 'dark'] as const) {
        for (const [size, viewport] of SIZES) {
          await restoreVault();                      // every shot starts from the seeded demo: nothing remembered yet
          const ctx = await browser.newContext({ viewport, baseURL: `http://localhost:${DEMO_PORT}` });
          await ctx.addInitScript((t) => { localStorage.setItem('steward-theme', t); }, theme);
          const page = await ctx.newPage();
          await loginAs(page, 'alex');
          await files(page, `${state}-${theme}-${size}`);
          if (state !== 'files') await toPreview(page);
          if (state === 'done' || state === 'layouts') await toDone(page);
          if (state === 'layouts') {
            await page.getByText(/· last used/).first().waitFor();       // a real row, not the empty note
            await page.getByRole('heading', { name: 'Remembered layouts' }).scrollIntoViewIfNeeded();
          }
          await settle(page);
          await page.screenshot({ path: `${OUT}/${state}-${size}-${theme}.png` });
          await ctx.close();
        }
      }
    }
  });
});
