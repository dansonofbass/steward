import { test, type Page } from '@playwright/test';
import { loginAs, restoreVault } from './fixtures';
import { DEMO_PORT } from './ports';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

declare const process: { env: Record<string, string | undefined> };
const TASK = process.env.SHOTS_TASK;
/** ready: a test id on screen once the page has its data, or "heading:{name}". */
type Shot = { name: string; path: string; ready: string; act?: (page: Page) => Promise<void> };
async function isReady(page: Page, ready: string) {
  if (ready.startsWith('heading:')) await page.getByRole('heading', { name: ready.slice('heading:'.length) }).first().waitFor();
  else await page.getByTestId(ready).first().waitFor();
}
const openFirst = async (page: Page) => { await page.getByTestId('txn-row').first().click(); await page.getByTestId('note-form').waitFor(); };

const SHOTS: Record<string, Shot[]> = {
  '4': [
    { name: 'detail-form', path: '/transactions?q=DISNEYPLUS&dates=all', ready: 'txn-row', act: openFirst },
    { name: 'list-named', path: '/transactions?q=DISNEYPLUS&dates=all', ready: 'txn-row', act: async (page) => {
      await openFirst(page);
      await page.getByLabel('Name').fill('Disney+');
      await page.getByRole('button', { name: 'Save' }).first().click();
      await page.getByTestId('undo-toast').waitFor();
    } },
    // A rule with an amount and a name, made the way the form makes one: a name with "And future ones" on a PayPal row.
    { name: 'rules', path: '/settings/rules', ready: 'heading:Category rules', act: async (page) => {
      await page.evaluate(async () => {
        const base = location.pathname.split('/settings')[0];
        const list = await (await fetch(`/api${base}/transactions?q=DISNEYPLUS`)).json();
        const id = list.transactions[0].id;
        const res = await fetch(`/api${base}/transactions/${id}/label`, { method: 'PUT', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ note: null, nickname: 'Disney+', also: false, future: true }) });
        if (!res.ok) throw new Error(`label ${res.status}`);
      });
      await page.reload();
      await page.getByText('Disney+').first().waitFor();
    } },
  ],
  '5': [
    { name: 'review-note', path: '/review', ready: 'review-card', act: async (page) => {
      await page.getByTestId('review-card').first().getByRole('button', { name: 'Note' }).click();
      await page.getByTestId('note-form').waitFor();
    } },
  ],
};
const SIZES = [['1280x800', { width: 1280, height: 800 }], ['390x844', { width: 390, height: 844 }]] as const;
// Playwright runs from web/ and creates the folder when it saves.
const OUT = `../.superpowers/sdd/2026-10-30-steward-polish-2/shots/task-${TASK}`;

test.describe('polish round, notes: screenshots', () => {
  test.skip(!TASK || !SHOTS[TASK], 'set SHOTS_TASK to a task with screens');
  test('each screen at both sizes, light and dark', async ({ browser }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'one run is enough');
    test.setTimeout(600_000);
    for (const shot of SHOTS[TASK!]) {
      for (const theme of ['light', 'dark'] as const) {
        for (const [size, viewport] of SIZES) {
          const ctx = await browser.newContext({ viewport, baseURL: `http://localhost:${DEMO_PORT}` });
          await ctx.addInitScript((t) => { localStorage.setItem('steward-theme', t); }, theme);
          const page = await ctx.newPage();
          await loginAs(page, 'alex');
          await page.goto(shot.path);
          await isReady(page, shot.ready);
          await shot.act?.(page);
          await page.evaluate(() => Promise.all([document.fonts.ready, ...document.getAnimations().map((a) => a.finished.catch(() => null))]));
          await page.screenshot({ path: `${OUT}/${shot.name}-${size}-${theme}.png`, fullPage: true });
          await ctx.close();
        }
      }
    }
  });
});
