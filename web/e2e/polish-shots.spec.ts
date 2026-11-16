import { test, type Page } from '@playwright/test';
import { loginAs, restoreVault } from './fixtures';
import { DEMO_PORT } from './ports';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

declare const process: { env: Record<string, string | undefined> };
const TASK = process.env.SHOTS_TASK;
/** ready: a test id that is on screen once the page has its data, or "heading:{name}" for a heading. */
type Shot = { name: string; path: string; ready: string; act?: (page: Page) => Promise<void> };
async function isReady(page: Page, ready: string) {
  if (ready.startsWith('heading:')) await page.getByRole('heading', { name: ready.slice('heading:'.length) }).first().waitFor({ timeout: 30_000 });
  else await page.getByTestId(ready).first().waitFor({ timeout: 30_000 });
}

/** Opens the inline Giving outside form on Spending's Giving row, when the demo shows one. */
async function openGiving(page: Page) {
  const add = page.getByRole('button', { name: 'Add it' });
  if (await add.count()) await add.first().click();
}

// Each task's screens, in the demo household.
const SHOTS: Record<string, Shot[]> = {
  '4': [
    { name: 'spending-month', path: '/spending', ready: 'sp-total' },
    { name: 'spending-giving-form', path: '/spending', ready: 'sp-total', act: openGiving },
    { name: 'category-giving', path: '/spending/giving', ready: 'cat-total' },
    { name: 'targets', path: '/spending/targets', ready: 'heading:Set targets' },
  ],
  '5': [
    { name: 'home', path: '/', ready: 'verdict' },
    { name: 'spending-month', path: '/spending', ready: 'sp-total' },
    { name: 'category-gifts', path: '/spending/gifts', ready: 'cat-total' },
    { name: 'trends', path: '/spending/trends', ready: 'trend-card' },
    { name: 'targets', path: '/spending/targets', ready: 'sumcard' },
  ],
  '7': [
    { name: 'setasides', path: '/spending/setasides', ready: 'sa-suggestions' },
    { name: 'setasides-picked', path: '/spending/setasides', ready: 'sa-suggestions',
      act: async (page) => { const boxes = page.getByTestId('sa-suggestion').getByRole('checkbox'); if (await boxes.count() > 1) { await boxes.nth(0).check(); await boxes.nth(1).check(); } } },
  ],
  '8': [
    { name: 'how', path: '/plan/how', ready: 'heading:What moves your plan most' },
    { name: 'how-open', path: '/plan/how', ready: 'heading:What moves your plan most',
      act: async (page) => { for (const name of ['Markets', 'Costs and withdrawals']) await page.locator('summary', { hasText: name }).click(); } },
  ],
};
const SIZES = [['1280x800', { width: 1280, height: 800 }], ['390x844', { width: 390, height: 844 }]] as const;
// Playwright runs from web/ and creates the folder when it saves.
const OUT = `../.superpowers/sdd/2026-10-30-steward-polish-1/shots/task-${TASK}`;

test.describe('polish round screenshots', () => {
  test.skip(!TASK || !SHOTS[TASK], 'set SHOTS_TASK to a task with screens');
  test('each screen at both sizes, light and dark', async ({ browser }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'one run is enough');
    test.setTimeout(600_000);
    // SHOTS_ONLY=name narrows a re-shoot to one screen.
    for (const shot of SHOTS[TASK!].filter((s) => !process.env.SHOTS_ONLY || s.name === process.env.SHOTS_ONLY)) {
      for (const theme of ['light', 'dark'] as const) {
        for (const [size, viewport] of SIZES) {
          const ctx = await browser.newContext({ viewport, baseURL: `http://localhost:${DEMO_PORT}` });
          await ctx.addInitScript((t) => { localStorage.setItem('steward-theme', t); }, theme);
          const page = await ctx.newPage();
          await loginAs(page, 'alex');
          await page.goto(shot.path);
          await isReady(page, shot.ready);
          await shot.act?.(page);
          // Fonts, and any transition the act started, settle before the shot.
          await page.evaluate(() => Promise.all([document.fonts.ready, ...document.getAnimations().map((a) => a.finished.catch(() => null))]));
          await page.screenshot({ path: `${OUT}/${shot.name}-${size}-${theme}.png`, fullPage: true });
          await ctx.close();
        }
      }
    }
  });
});
