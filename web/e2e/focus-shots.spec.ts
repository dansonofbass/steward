import { test, type Page } from '@playwright/test';
import { listView, loginAs, restoreVault } from './fixtures';
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
/** Leave the household's matching rows for the box test: untick "Also the N like it" where it shows. */
async function untick(scope: ReturnType<Page['locator']>) {
  const also = scope.getByRole('checkbox', { name: /^Also the / });
  if (await also.count()) await also.uncheck();
}

/** A touch drag on the current card, held (no pointerup), then two frames so the transform and the label are painted. */
async function midSwipe(page: Page, dx: number, dy: number) {
  await page.locator('[data-testid=focus-card][data-role=current]').evaluate(async (el, [x, y]) => {
    const r = el.getBoundingClientRect();
    const at = (type: string, cx: number, cy: number) => el.dispatchEvent(new PointerEvent(type,
      { bubbles: true, cancelable: true, pointerId: 7, pointerType: 'touch', isPrimary: true, clientX: cx, clientY: cy }));
    const x0 = r.left + r.width / 2;
    const y0 = r.top + r.height / 2;
    at('pointerdown', x0, y0);
    at('pointermove', x0 + x / 2, y0 + y / 2);
    at('pointermove', x0 + x, y0 + y);
    await new Promise<void>((done) => { requestAnimationFrame(() => { requestAnimationFrame(() => { done(); }); }); });
  }, [dx, dy] as const);
}

const SHOTS: Record<string, Shot[]> = {
  '4': [
    { name: 'list-slim-toast', path: '/review', ready: 'review-top', act: async (page) => {
      await listView(page);
      const card = page.getByTestId('review-card').first();
      await untick(card);
      await card.locator('.chips button:not(.chip--more)').first().click();
      await page.getByTestId('slim-row').first().waitFor();
      await page.locator('.undo-toast').waitFor();
    } },
  ],
  '5': [
    { name: 'focus', path: '/review', ready: 'focus-card' },
    { name: 'focus-toast', path: '/review', ready: 'focus-card', act: async (page) => {
      const card = page.locator('[data-testid=focus-card][data-role=current]');
      await untick(card);
      await card.locator('.chips button:not(.chip--more)').first().click();
      await page.locator('.undo-toast').waitFor();
    } },
  ],
  '6': [
    { name: 'focus-menu', path: '/review', ready: 'focus-card', act: async (page) => {
      await page.locator('[data-testid=focus-card][data-role=current]').getByRole('button', { name: 'More actions' }).click();
      await page.getByRole('menu', { name: 'More actions' }).waitFor();
    } },
    { name: 'focus-note', path: '/review', ready: 'focus-card', act: async (page) => {
      const card = page.locator('[data-testid=focus-card][data-role=current]');
      await card.getByRole('button', { name: 'More actions' }).click();
      await page.getByRole('menuitem', { name: 'Add note' }).click();
      await card.getByTestId('note-form').waitFor();
    } },
  ],
  '7': [
    { name: 'focus-midswipe-right', path: '/review', ready: 'focus-card', act: (page) => midSwipe(page, 160, 0) },
    { name: 'focus-midswipe-left', path: '/review', ready: 'focus-card', act: (page) => midSwipe(page, -80, 0) },
    { name: 'focus-midswipe-up', path: '/review', ready: 'focus-card', act: (page) => midSwipe(page, 0, -160) },
  ],
  '8': [
    { name: 'appearance', path: '/you/appearance', ready: 'heading:Appearance' },
    { name: 'focus-hint', path: '/review', ready: 'focus-card' },
  ],
};
const SIZES = [['1280x800', { width: 1280, height: 800 }, false], ['390x844', { width: 390, height: 844 }, true]] as const;
// Playwright runs from web/ and creates the folder when it saves.
const OUT = `../.superpowers/sdd/2026-10-30-steward-review-focus/shots/task-${TASK}`;

test.describe('review focus: screenshots', () => {
  test.skip(!TASK || !SHOTS[TASK], 'set SHOTS_TASK to a task with screens');
  test('each screen at both sizes, light and dark', async ({ browser }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'one run is enough');
    test.setTimeout(600_000);
    for (const shot of SHOTS[TASK!]) {
      for (const theme of ['light', 'dark'] as const) {
        for (const [size, viewport, touch] of SIZES) {
          // The phone size is a touch screen (a coarse pointer), as the hint and the swipes need.
          const ctx = await browser.newContext({ viewport, hasTouch: touch, baseURL: `http://localhost:${DEMO_PORT}` });
          await ctx.addInitScript((t) => { localStorage.setItem('steward-theme', t); localStorage.setItem('steward-swipe-demo', 'nudged'); }, theme);
          const page = await ctx.newPage();
          await loginAs(page, 'alex');
          await page.goto(shot.path);
          await isReady(page, shot.ready);
          await shot.act?.(page);
          await page.evaluate(() => Promise.all([document.fonts.ready, ...document.getAnimations().map((a) => a.finished.catch(() => null))]));
          await page.screenshot({ path: `${OUT}/${shot.name}-${size}-${theme}.png` });   // the viewport: the review queue is thousands of px tall
          await ctx.close();
        }
      }
    }
  });
});
