import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test';
import { bankFiles, chatOn, listView, loginAs, monthEnd, restoreVault, serverDay, statementPdf, upload, youMenu } from './fixtures';
import { DEMO_PORT, EMPTY_PORT } from './ports';

// Phase 17, dark mode and foundations: the screenshot gate (spec 2.8). Every screen at 1280x800 and 390x844, light and
// dark, viewport only, grown from the p17 audit's spec. SHOTS_TASK picks a task's screens ("all" for every one), and
// SHOTS_ONLY=name,name narrows that. Without SHOTS_TASK it skips, so the full e2e run passes over it.
declare const process: { env: Record<string, string | undefined> };
const TASK = process.env.SHOTS_TASK;
const ONLY = process.env.SHOTS_ONLY ? new Set(process.env.SHOTS_ONLY.split(',')) : null;
// Playwright runs from web/ and creates the folder when it saves.
const OUT = `../.superpowers/sdd/2026-11-02-steward-p17-dark/shots/${TASK === 'all' ? 'all' : `task-${TASK}`}`;
const SIZES = [['1280x800', { width: 1280, height: 800 }], ['390x844', { width: 390, height: 844 }]] as const;
const THEMES = ['light', 'dark'] as const;
const PARENT = 'margaret-ellis-seed-desktop';
/** celebrate.ts's BURST_MS (STAMP_DELAY_MS + STAMP_MS - the streamers' 80 ms): e2e can't import the chunk (its CSS). */
const BURST_MS = 650;

const BY_TASK: Record<string, readonly string[]> = {
  '1': ['home', 'spending', 'spending-trends', 'plan', 'review-focus', 'accounts', 'appearance', 'settings-chat', 'profile', 'login', 'parent-home'],
  '2': ['home', 'spending-category', 'plan-how', 'transactions', 'review-list', 'parent-home', 'parent-settings-changes', 'focusring-spending', 'focusring-review'],
  '3': ['appearance', 'settings-business', 'export', 'settings-log', 'transaction-open', 'setaside-new', 'spending-trends', 'taxes', 'business', 'plan-try', 'review-focus'],
  '4': ['cel-sort', 'pop', 'youmenu', 'review-more', 'transaction-open'],
  '5': ['home', 'spending', 'spending-category', 'spending-trends', 'setasides', 'settings-chat', 'profile', 'plan-try', 'reimbursements', 'empty-plan'],
  '6': ['cel-sort-leaves', 'cel-sort-snow', 'cel-sunrise'],
  '7': ['parent-care', 'plan', 'spending', 'appearance', 'empty-review', 'review-caughtup', 'pop-quiet'],
};
const wanted = (name: string) => (ONLY ? ONLY.has(name) : TASK === 'all' || (BY_TASK[TASK ?? ''] ?? []).includes(name));
const log: string[] = [];

type Act = (page: Page) => Promise<void>;
type Shot = { name: string; path: string; act?: Act; before?: Act };

/** Ready to shoot: the data in (no skeleton or busy region; a heading or the queue on screen), fonts loaded, every finite
 *  animation done. Conditions with ceilings, never a delay; a miss goes to the log. */
async function settle(page: Page, name: string) {
  await page.waitForFunction(() => !document.querySelector('.skeleton, [aria-busy="true"]')
    && !!document.querySelector('h1, h2, .review__done, [data-testid=focus-card]'), null, { timeout: 20_000 })
    .catch(() => { log.push(`${name}: still loading after 20 s`); });
  await page.waitForLoadState('networkidle', { timeout: 8_000 }).catch(() => { log.push(`${name}: network never idle`); });
  await page.evaluate(async () => { await document.fonts.ready; });
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== 'running' || a.effect?.getComputedTiming().iterations === Infinity),
    null, { timeout: 5_000 }).catch(() => { log.push(`${name}: animations still running`); });
}

/** Anything past the right edge (a table scrolls in its own wrap) goes to the log for the reviewer. */
async function sideways(page: Page, name: string) {
  const over = await page.evaluate(() => [...document.querySelectorAll('body *')]
    .filter((e) => e.getBoundingClientRect().right > document.documentElement.clientWidth + 0.5 && !e.closest('.table-wrap'))
    .slice(0, 5).map((e) => `${e.tagName.toLowerCase()}.${e.getAttribute('class') ?? ''}`));
  if (over.length) log.push(`${name}: past the right edge: ${over.join(', ')}`);
}

/** Phase 17 (2.7): every tab in a section's row is whole on screen; on a phone the row wraps instead of cutting one. */
async function tabsWhole(page: Page) {
  const cut = await page.locator('.subnav a').evaluateAll((as) => as
    .filter((a) => a.getBoundingClientRect().right > document.documentElement.clientWidth + 0.5).map((a) => a.textContent));
  expect(cut).toEqual([]);
}

const firstHref = async (page: Page, sel: string) => {
  const a = page.locator(sel).first();
  await a.waitFor();
  return a.getAttribute('href');
};
const gotoFirst = (list: string, sel: string): Act => async (page) => {
  await page.goto(list);
  const href = await firstHref(page, sel);
  if (href) await page.goto(href);
};
/** Until n files are staged and none is still being read (a condition with the test's ceiling). */
const staged = async (page: Page, n: number) => {
  await page.waitForFunction((count) => document.querySelectorAll('li.imp-row').length === count && !document.querySelector('li.imp-row[aria-busy]'), n);
};

const HOUSEHOLD: Shot[] = [
  { name: 'home', path: '/b/ours' },
  { name: 'home-best', path: '/b/ours', before: async (page) => {
    await page.route(/\/api\/b\/ours\/home(\?.*)?$/, async (route) => {
      const res = await route.fetch(); const j = await res.json();
      await route.fulfill({ response: res, json: { ...j, verdict: { ...j.verdict, opener: 'steady', problems: [], best_month: true } } });
    });
  } },
  { name: 'youmenu', path: '/b/ours', act: async (page) => { await youMenu(page); await page.getByRole('dialog').first().waitFor(); } },
  { name: 'review-focus', path: '/b/ours/review', act: async (page) => { await page.getByTestId('focus-card').first().waitFor(); } },
  { name: 'review-more', path: '/b/ours/review', act: async (page) => {
    await page.locator('[data-testid=focus-card][data-role=current] .chip--more').click();
    await page.getByRole('dialog').first().waitFor();
  } },
  { name: 'review-list', path: '/b/ours/review', act: async (page) => { await listView(page); await page.getByTestId('review-card').first().waitFor(); } },
  { name: 'review-caughtup', path: '/b/ours/review', before: async (page) => {
    await page.route(/\/api\/b\/ours\/review(\?.*)?$/, async (route) => {
      const res = await route.fetch(); const j = await res.json();
      await route.fulfill({ response: res, json: { ...j, uncategorized: [], count: 0, duplicates: [], duplicate_count: 0, business: [], business_count: 0, background: undefined } });
    });
  } },
  { name: 'spending', path: '/b/ours/spending' },
  { name: 'spending-category', path: '/b/ours/spending/dining' },
  { name: 'spending-trends', path: '/b/ours/spending/trends' },
  { name: 'spending-targets', path: '/b/ours/spending/targets' },
  { name: 'setasides', path: '/b/ours/spending/setasides' },
  { name: 'setaside-page', path: '/b/ours/spending/setasides', act: gotoFirst('/b/ours/spending/setasides', 'a[href*="/spending/setasides/"]:not([href$="/new"])') },
  { name: 'setaside-new', path: '/b/ours/spending/setasides/new' },
  { name: 'reimbursements', path: '/b/ours/spending/reimbursements' },
  { name: 'plan', path: '/b/ours/plan' },
  { name: 'plan-try', path: '/b/ours/plan/try' },
  { name: 'plan-next', path: '/b/ours/plan/next' },
  { name: 'plan-how', path: '/b/ours/plan/how' },
  { name: 'accounts', path: '/b/ours/accounts' },
  { name: 'account-page', path: '/b/ours/accounts', act: gotoFirst('/b/ours/accounts', 'main a[href*="/accounts/"]') },
  { name: 'transactions', path: '/b/ours/transactions' },
  { name: 'transaction-open', path: '/b/ours/transactions', act: async (page) => {
    await page.getByTestId('txn-row').first().click();
    await page.getByTestId('txn-detail').waitFor();
  } },
  { name: 'ask', path: '/b/ours/ask' },
  { name: 'import', path: '/b/ours/settings/import' },
  { name: 'import-staged', path: '/b/ours/settings/import', act: async (page) => {
    const files = bankFiles(await serverDay(page));
    await page.locator('input[type=file]').first().setInputFiles([upload('amex-basic.csv', files['amex-basic.csv']), upload('bank.ofx', files['bank.ofx'])]);
    await staged(page, 2);
  } },
  { name: 'statements-staged', path: '/b/ours/settings/import', act: async (page) => {
    const end = monthEnd(await serverDay(page), 1);
    await page.locator('input[type=file]').first().setInputFiles([
      await statementPdf(page, 'Statement_checking.pdf', 'chase_checking', end),
      await statementPdf(page, 'Stmt_off.pdf', 'boa_checking', end, 'off'),
      await statementPdf(page, 'protected.pdf', 'citi_card', end, 'password')]);
    await page.getByText('This PDF has a password', { exact: false }).first().waitFor();
    await staged(page, 3);
  } },
  { name: 'export', path: '/b/ours/settings/export' },
  { name: 'settings', path: '/b/ours/settings' },
  ...['members', 'book', 'books', 'banks', 'rules', 'business', 'chat', 'log'].map((s) => ({ name: `settings-${s}`, path: `/b/ours/settings/${s}` })),
  { name: 'appearance', path: '/b/ours/you/appearance' },
  { name: 'devices', path: '/b/ours/you/devices' },
  { name: 'profile', path: '/b/ours/profile' },
  { name: 'profile-kids', path: '/b/ours/profile/kids' },
  { name: 'taxes', path: '/b/ours/taxes' },
  { name: 'business', path: '/b/ours/business' },
];

const PARENT_SHOTS: Shot[] = [
  { name: 'parent-home', path: `/b/${PARENT}` },
  { name: 'parent-care', path: `/b/${PARENT}/care` },
  { name: 'parent-inventory', path: `/b/${PARENT}/inventory` },
  { name: 'parent-item', path: `/b/${PARENT}/inventory`, act: async (page) => { await page.getByTestId('item-row').first().click(); } },
  { name: 'parent-lookinto', path: `/b/${PARENT}/look-into` },
  { name: 'parent-review', path: `/b/${PARENT}/review` },
  { name: 'parent-transactions', path: `/b/${PARENT}/transactions` },
  { name: 'parent-settings-watching', path: `/b/${PARENT}/settings/watching` },
  { name: 'parent-settings-changes', path: `/b/${PARENT}/settings/changes` },
];

const EMPTY_SHOTS: Shot[] = [
  { name: 'empty-home', path: '/b/ours' },
  { name: 'empty-review', path: '/b/ours/review' },
  { name: 'empty-spending', path: '/b/ours/spending' },
  { name: 'empty-accounts', path: '/b/ours/accounts' },
  { name: 'empty-transactions', path: '/b/ours/transactions' },
  { name: 'empty-plan', path: '/b/ours/plan' },
  { name: 'empty-reimbursements', path: '/b/ours/spending/reimbursements' },
  { name: 'empty-setasides', path: '/b/ours/spending/setasides' },
];

const SIGNED_OUT: Shot[] = [{ name: 'login', path: '/login' }, { name: 'forgot', path: '/forgot' }];

async function context(browser: Browser, port: number, theme: string, viewport: { width: number; height: number }, userId?: number, reduce = false) {
  const ctx = await browser.newContext({ viewport, baseURL: `http://localhost:${port}`, deviceScaleFactor: 1, reducedMotion: reduce ? 'reduce' : 'no-preference' });
  await ctx.addInitScript(([t, id]) => {
    localStorage.setItem('steward-theme', t as string);
    if (id) localStorage.setItem(`steward-ask-tour:${id}`, 'done');
    localStorage.setItem('steward-swipe-demo', 'done');
  }, [theme, userId ?? 0] as [string, number]);
  return ctx;
}

async function shootAll(ctx: BrowserContext, shots: Shot[], size: string, theme: string, failed: string[]) {
  for (const shot of shots) {
    const page = await ctx.newPage();
    try {
      await shot.before?.(page);
      await page.goto(shot.path);
      await settle(page, shot.name);
      if (shot.act) { await shot.act(page); await settle(page, shot.name); }
      await sideways(page, shot.name);
      if (await page.locator('.subnav').count()) await tabsWhole(page);
      await page.screenshot({ path: `${OUT}/${shot.name}-${size}-${theme}.png` });
    } catch (e) {
      failed.push(`${shot.name}-${size}-${theme}: ${(e as Error).message.split('\n')[0]}`);
    }
    await page.close();
  }
}

/** Holds the DOM's own motion for a still: the pop at 400 ms (fully in), every other finite animation finished. */
async function holdMotion(page: Page) {
  await page.evaluate(() => {
    for (const a of document.getAnimations()) {
      if (a.effect?.getComputedTiming().iterations === Infinity) continue;
      const target = (a.effect as KeyframeEffect | null)?.target ?? null;
      if (target?.classList.contains('cel-pop')) { a.pause(); a.currentTime = 400; } else a.finish();
    }
  });
}

/** Installs Playwright's clock and pauses it, so only runFor moves time (install alone keeps real time flowing). */
async function pausedClock(page: Page, time?: Date) {
  const t0 = time ?? new Date();
  await page.clock.install({ time: t0 });
  await page.clock.pauseAt(new Date(t0.getTime() + 1000));
}

async function sortFirst(page: Page) {
  const card = page.locator('[data-testid=focus-card][data-role=current]');
  await card.waitFor();
  const also = card.getByRole('checkbox', { name: /^Also the / });
  if (await also.count()) await also.uncheck();
  await card.locator('.chips button:not(.chip--more)').first().click();
}

/** A sort mid-burst (and, for plain cel-sort, after it), on Playwright's paused clock: the canvas's frames and the toast's
 *  timer move only when runFor says. `time` fixes the date for a season. */
async function celSort(page: Page, name: string, shot: (n: string) => Promise<void>, time?: Date) {
  await page.goto('/b/ours/review');
  await settle(page, name);
  await pausedClock(page, time);
  await sortFirst(page);
  await page.locator('.cel-stamp').first().waitFor({ state: 'attached' });
  await page.clock.runFor(BURST_MS + 220);
  await holdMotion(page);
  await page.locator('.undo-toast').waitFor();
  await shot(name);
  if (name === 'cel-sort') { await page.clock.runFor(1600); await shot('cel-sort-after'); }
}

/** The last card goes: All caught up, the sunrise mid-rise, then the cheer. */
async function celSunrise(page: Page, shot: (n: string) => Promise<void>) {
  let calls = 0;
  await page.route(/\/api\/b\/ours\/review(\?.*)?$/, async (route) => {
    const res = await route.fetch(); const j = await res.json();
    calls += 1;
    const keep = calls === 1 ? j.uncategorized.slice(0, 1) : [];
    await route.fulfill({ response: res, json: { ...j, uncategorized: keep, count: keep.length, duplicates: [], duplicate_count: 0, business: [], business_count: 0, background: undefined } });
  });
  await page.goto('/b/ours/review');
  await settle(page, 'cel-sunrise');
  await pausedClock(page);
  await sortFirst(page);
  const done = page.locator('.review__done');
  await expect.poll(async () => { await page.clock.runFor(100); return done.isVisible(); }).toBe(true);
  await page.clock.runFor(700);
  await holdMotion(page);
  await shot('cel-sunrise');
  await page.clock.runFor(2200);
  await shot('cel-caughtup-cheer');
}

/** The 100th sort on this device: the milestone pop (motion on), or its words under the top bar (motion off). */
async function popShot(page: Page, name: 'pop' | 'pop-quiet', shot: (n: string) => Promise<void>) {
  await page.goto('/b/ours/review');
  await page.evaluate(() => { localStorage.setItem('steward-sorts', JSON.stringify({ total: 99 })); });
  await page.reload();
  await settle(page, name);
  await pausedClock(page);
  await sortFirst(page);
  if (name === 'pop') await page.locator('.cel-pop').waitFor({ state: 'attached' });
  else await page.locator('.review__said').waitFor();
  await holdMotion(page);
  await page.locator('.undo-toast').waitFor();
  await shot(name);
}

async function focusRing(page: Page, name: string, path: string, tabs: number, shot: (n: string) => Promise<void>) {
  await page.goto(path);
  await settle(page, name);
  for (let i = 0; i < tabs; i++) await page.keyboard.press('Tab');
  await shot(name);
}

test.describe('phase 17 shots', () => {
  test.skip(!TASK, 'SHOTS_TASK picks the screens to shoot');
  test.afterAll(() => { for (const l of log) console.log(`P17LOG ${l}`); });

  test('every screen, both sizes, light and dark', async ({ browser }, info) => {
    test.skip(info.project.name !== 'desktop', 'one run is enough');
    const out = SIGNED_OUT.filter((s) => wanted(s.name));
    const ours = [...HOUSEHOLD, ...PARENT_SHOTS].filter((s) => wanted(s.name));
    const empty = EMPTY_SHOTS.filter((s) => wanted(s.name));
    const n = out.length + ours.length + empty.length;
    test.skip(n === 0, 'no screens in this task');
    test.setTimeout(120_000 + n * 4 * 20_000);
    const failed: string[] = [];
    for (const theme of THEMES) {
      for (const [size, viewport] of SIZES) {
        await restoreVault();   // staged imports from the last pass would show on Import
        if (out.length) {
          const ctx = await context(browser, DEMO_PORT, theme, viewport);
          await shootAll(ctx, out, size, theme, failed);
          await ctx.close();
        }
        if (ours.length) {
          const setup = await browser.newPage({ baseURL: `http://localhost:${DEMO_PORT}` });
          await loginAs(setup, 'alex');
          await chatOn(setup, 'ours');
          await setup.request.post('/api/b/ours/chat/seen', { data: {} });
          const me = (await (await setup.request.get('/api/auth/me')).json()) as { user: { id: number } };
          await setup.close();
          const ctx = await context(browser, DEMO_PORT, theme, viewport, me.user.id);
          const p = await ctx.newPage(); await loginAs(p, 'alex'); await p.close();
          await shootAll(ctx, ours, size, theme, failed);
          await ctx.close();
        }
        if (empty.length) {
          const ctx = await context(browser, EMPTY_PORT.desktop, theme, viewport);
          const e = await ctx.newPage(); await loginAs(e, 'alex'); await e.close();
          await shootAll(ctx, empty, size, theme, failed);
          await ctx.close();
        }
      }
    }
    expect(failed).toEqual([]);
  });

  test('celebrations, the pop and the focus rings', async ({ browser }, info) => {
    test.skip(info.project.name !== 'desktop', 'one run is enough');
    const flows = ['cel-sort', 'cel-sort-leaves', 'cel-sort-snow', 'cel-sunrise', 'pop', 'pop-quiet', 'focusring-spending', 'focusring-review'].filter(wanted);
    test.skip(flows.length === 0, 'no celebrations in this task');
    test.setTimeout(120_000 + flows.length * 4 * 30_000);
    await restoreVault();
    const failed: string[] = [];
    for (const theme of THEMES) {
      for (const [size, viewport] of SIZES) {
        for (const flow of flows) {
          const ctx = await context(browser, DEMO_PORT, theme, viewport, undefined, flow === 'pop-quiet');
          const page = await ctx.newPage();
          await loginAs(page, 'alex');
          const shot = async (n: string) => { await page.screenshot({ path: `${OUT}/${n}-${size}-${theme}.png` }); };
          try {
            if (flow === 'cel-sort') await celSort(page, flow, shot);
            else if (flow === 'cel-sort-leaves') await celSort(page, flow, shot, new Date(2026, 10, 15, 12));
            else if (flow === 'cel-sort-snow') await celSort(page, flow, shot, new Date(2026, 11, 10, 12));
            else if (flow === 'cel-sunrise') await celSunrise(page, shot);
            else if (flow === 'pop' || flow === 'pop-quiet') await popShot(page, flow, shot);
            else if (flow === 'focusring-spending') await focusRing(page, flow, '/b/ours/spending', 6, shot);
            else await focusRing(page, flow, '/b/ours/review', 8, shot);
          } catch (e) {
            failed.push(`${flow}-${size}-${theme}: ${(e as Error).message.split('\n')[0]}`);
          }
          await ctx.close();
        }
      }
    }
    expect(failed).toEqual([]);
  });
});
