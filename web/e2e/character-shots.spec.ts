import { test, type Browser, type Page } from '@playwright/test';
import { animationsSettled, loginAs, restoreVault } from './fixtures';
import { DEMO_PORT } from './ports';

// Phase 17, PR 2 (character): the screenshot gate. Each task's states at 1280x800 and 390x844, light and dark, the
// viewport only. SHOTS_TASK=N takes task N's shots; SHOTS_TASK=all takes them all (Task 9).
declare const process: { env: Record<string, string | undefined> };
declare const Buffer: { from(s: string): never };   // the e2e tsconfig carries no node types
const TASK = process.env.SHOTS_TASK;
const OUT = `../.superpowers/sdd/2026-11-02-steward-p17-character/shots/task-${TASK}`;
const SIZES = [['1280x800', { width: 1280, height: 800 }], ['390x844', { width: 390, height: 844 }]] as const;
const THEMES = ['light', 'dark'] as const;
const wants = (n: string) => TASK === n || TASK === 'all';

test.beforeAll(async () => { await restoreVault(); });

type Step = (page: Page) => Promise<void>;
const nothing: Step = async () => {};

/** One state, both sizes, both themes. `prep` runs before the page opens (routes, init scripts); `ready` waits for it. */
async function shoot(browser: Browser, name: string, path: string, ready: Step, prep: Step = nothing, user: string | null = 'alex', fresh = false) {
  for (const theme of THEMES) {
    for (const [size, viewport] of SIZES) {
      if (fresh) await restoreVault();   // a state that changes the books starts every combination from the same queue
      const ctx = await browser.newContext({ viewport, baseURL: `http://localhost:${DEMO_PORT}` });
      await ctx.addInitScript((t) => { localStorage.setItem('steward-theme', t); }, theme);
      const page = await ctx.newPage();
      if (user) await loginAs(page, user);
      await prep(page);
      await page.goto(path);
      await ready(page);
      await page.evaluate(() => document.fonts.ready);
      await animationsSettled(page);
      await page.screenshot({ path: `${OUT}/${name}-${size}-${theme}.png` });
      await ctx.close();
    }
  }
  if (fresh) await restoreVault();
}

test.describe('character screenshots (phase 17 PR 2)', () => {
  test.skip(!TASK, 'set SHOTS_TASK to a task number, or all');
  test.beforeEach(({}, testInfo) => { test.skip(testInfo.project.name !== 'desktop', 'one run takes both sizes'); });

  test('task 1: the four faces and both seasons, on the design page', async ({ browser }) => {
    test.skip(!wants('1'));
    test.setTimeout(300_000);
    await shoot(browser, 'faces', '/design', async (page) => { await page.locator('svg.acorn').first().waitFor();
      await page.locator('.theme-dark svg.acorn').first().scrollIntoViewIfNeeded(); }, nothing, null);
  });

  test('task 6: the greeting and the tree on Home, payday, and the tree on Profile', async ({ browser }) => {
    test.skip(!wants('6'));
    test.setTimeout(600_000);
    const homeWith = (extra: (h: Record<string, any>) => Record<string, any>) => async (page: Page) => {
      await page.route(/\/api\/b\/ours\/home(\?.*)?$/, async (route) => {
        const res = await route.fetch();
        await route.fulfill({ response: res, json: extra((await res.json()) as Record<string, any>) });
      });
    };
    const steady = (h: Record<string, any>) => ({ ...h, verdict: { ...h.verdict, opener: 'steady', problems: [] },
      flow: { ...h.flow, in_cents: 638_000, out_cents: 514_000, net_cents: 124_000, payday: null } });
    const tree = async (page: Page) => {
      await page.route(/\/api\/b\/ours\/growth$/, (r) => r.fulfill({ json: { stage: 3, seen: false, milestones: [
        { key: 'first_month', met: true }, { key: 'covered', met: false }, { key: 'checklist', met: true }, { key: 'year', met: true }, { key: 'five_years', met: false }] } }));
      await page.route(/\/api\/b\/ours\/growth\/seen$/, (r) => r.fulfill({ status: 204 }));
    };
    const homeReady = async (page: Page) => { await page.getByTestId('verdict').and(page.locator('[data-ready=true]')).waitFor(); await page.getByTestId('home-tree').waitFor(); await page.getByTestId('home-tree').scrollIntoViewIfNeeded(); };
    await shoot(browser, 'home-tree', '/b/ours', homeReady, async (page) => { await homeWith(steady)(page); await tree(page); });
    await shoot(browser, 'home-payday', '/b/ours', async (page) => { await page.getByTestId('payday-came').waitFor(); },
      homeWith((h) => ({ ...steady(h), flow: { ...steady(h).flow, payday_came: { day: 1 } } })));
    await shoot(browser, 'profile-growth', '/b/ours/profile', async (page) => { await page.getByTestId('profile-growth').evaluate((el) => el.scrollIntoView({ block: 'center' })); }, tree);
  });

  test('task 5: the toast with a cheer, a golden toast, and All caught up', async ({ browser }) => {
    test.skip(!wants('5'));
    test.setTimeout(600_000);
    const sortTimes = (n: number) => async (page: Page) => {
      const card = page.locator('[data-testid=focus-card][data-role=current]');
      for (let i = 0; i < n; i++) {
        const id = await card.getAttribute('data-id');
        const also = card.getByRole('checkbox', { name: /^Also the / });
        if (await also.count()) await also.uncheck();
        await card.locator('.chips button:not(.chip--more)').first().click();
        await card.and(page.locator(`:not([data-id="${id}"])`)).waitFor();
      }
      await page.locator('.undo-toast').waitFor();
    };
    const random = (v: number) => async (page: Page) => { await page.addInitScript((x) => { Math.random = () => x; }, v); };
    await shoot(browser, 'toast-cheer', '/b/ours/review', sortTimes(4), random(0.5), 'spouse', true);
    await shoot(browser, 'toast-golden', '/b/ours/review', sortTimes(1), random(0.01), 'spouse', true);
    const nothingLeft = async (page: Page) => {
      await page.route(/\/api\/b\/ours\/review$/, (r) => r.fulfill({ json: {
        uncategorized: [], count: 0, sorted_count: 0, duplicates: [], duplicate_count: 0, top_categories: [], business: [], business_count: 0,
        background: { pending: 0, done: 0, waiting: false }, empty: false } }));
    };
    await shoot(browser, 'caught-up', '/b/ours/review', async (page) => { await page.getByTestId('caught-up-line').waitFor(); await page.locator('[aria-busy=true]').waitFor({ state: 'detached' }); }, nothingLeft);
  });

  test('task 7: an import hiccup, Profile at 5 of 5 and a set-aside covered early', async ({ browser }) => {
    test.skip(!wants('7'));
    test.setTimeout(600_000);
    const refuse = async (page: Page) => {
      await page.route(/\/api\/b\/ours\/import\/files(\?.*)?$/, (r) => r.fulfill({ status: 422, json: { error: "Steward can't read this file." } }));
    };
    await shoot(browser, 'import-oops', '/b/ours/settings/import', async (page) => {
      await page.locator('input[type=file]').setInputFiles({ name: 'odd.csv', mimeType: 'text/csv', buffer: Buffer.from('a,b\n1,2\n') });
      await page.locator('.imp-row svg.acorn').waitFor();
    }, refuse);
    const profileDone = async (page: Page) => {
      await page.route(/\/api\/b\/ours\/profile$/, async (route) => {
        const res = await route.fetch();
        const j = (await res.json()) as { sections: { status: string }[]; total: number };
        await route.fulfill({ response: res, json: { ...j, done: j.total, sections: j.sections.map((s) => ({ ...s, status: 'done' })) } });
      });
    };
    await shoot(browser, 'profile-done', '/b/ours/profile', async (page) => { await page.getByTestId('profile-done').waitFor(); }, profileDone);
    const covered = async (page: Page) => {
      await page.route(/\/api\/b\/ours\/setasides$/, async (route) => {
        const res = await route.fetch();
        const j = (await res.json()) as { rows: Record<string, unknown>[] };
        // The demo book has no set-asides, so this one is made up in the answer (the shape the API gives).
        const made = { id: 9001, name: 'Property tax', kind: 'yearly', amount_cents: 421_000, monthly_cents: 35_100, yearly_cents: 421_000,
          installment_cents: 421_000, due_month: 11, due_day: 20, second_month: null, second_day: null, due_year: null, first_month: '2026-01-01',
          next_due: '2026-11-20', days_until: 21, missed_due: null, is_estimate: false, estimate: null,
          account: { id: 1, name: 'House fund', balance_cents: 900_000, as_of: '2026-10-29', stale: false, shared_with: [] },
          put_away_cents: 421_000, should_cents: 351_000, state: 'on_track', short_cents: 0, behind_cents: 0, counted_from: '2026-01-01',
          payee_key: null, payee_name: null, category: null, notes: null, paid: null, archived_at: null };
        await route.fulfill({ response: res, json: { ...j, rows: [made, ...j.rows], count: j.rows.length + 1 } });
      });
    };
    await shoot(browser, 'setaside-covered', '/b/ours/spending/setasides', async (page) => { await page.getByTestId('sa-covered').waitFor(); }, covered);
  });

  test('task 8: waiting for the gateway, and a failed sync', async ({ browser }) => {
    test.skip(!wants('8'));
    test.setTimeout(600_000);
    const waiting = async (page: Page) => {
      await page.route(/\/api\/b\/ours\/review$/, async (route) => {
        const res = await route.fetch();
        await route.fulfill({ response: res, json: { ...(await res.json()), background: { pending: 14, done: 0, waiting: true } } });
      });
    };
    await shoot(browser, 'review-waiting', '/b/ours/review', async (page) => { await page.locator('[data-testid=review-background] svg.acorn').waitFor(); }, waiting);
    await shoot(browser, 'home-waiting', '/b/ours', async (page) => {
      await page.locator('[data-testid=background-line] svg.acorn').waitFor();
      await page.getByTestId('background-line').scrollIntoViewIfNeeded();
    }, waiting);
    const syncFailed = async (page: Page) => {
      await page.route(/\/api\/b\/ours\/simplefin$/, (r) => r.fulfill({ json: { linked: true, last_sync_at: '2026-10-29T15:00:00Z',
        last_error: "The bank didn't answer. Steward tries again in an hour." } }));
    };
    const awayLong = async (page: Page) => {
      await page.route(/\/api\/auth\/me$/, async (route) => {   // chat on in every book, so Home asks the gateway's state
        const res = await route.fetch();
        const j = await res.json() as { books: { chat?: boolean }[] };
        await route.fulfill({ response: res, json: { ...j, books: j.books.map((b) => ({ ...b, chat: true })) } });
      });
      await page.route(/\/api\/b\/ours\/chat$/, (r) => r.fulfill({ json: { on: true, gateway: { state: 'away', line: '', last_answered: null,
        checked: null, checks: null, away_long: true } } }));
    };
    await shoot(browser, 'home-gateway-off', '/b/ours', async (page) => {
      await page.getByTestId('gateway-off').locator('svg.acorn').waitFor();
      await page.getByTestId('gateway-off').scrollIntoViewIfNeeded();
    }, awayLong);
    await shoot(browser, 'banks-sync-failed', '/b/ours/settings/banks', async (page) => { await page.locator('.warn svg.acorn').waitFor(); }, syncFailed);
  });
});
