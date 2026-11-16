import { test } from '@playwright/test';
import { animationsSettled, chatOn, loginAs, restoreVault } from './fixtures';
import { DEMO_PORT } from './ports';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

declare const process: { env: Record<string, string | undefined> };
const TASK = process.env.SHOTS_TASK;
// Playwright runs from web/ and creates the folder when it saves.
const OUT = `../.superpowers/sdd/2026-10-31-steward-ask-about/shots/task-${TASK}`;
const SIZES = [['1280x800', { width: 1280, height: 800 }], ['390x844', { width: 390, height: 844 }]] as const;
type Status = Record<string, unknown> & { gateway: Record<string, unknown>; budget: Record<string, unknown> | null };
/** The gate's four states: ready, the first-use highlight, the gateway away and the budget used up (the last two by
 *  patching the server's own status). The cap line is a screenshot fixture (plan-owned). */
const STATES: Record<string, { tour: boolean; patch?: (s: Status) => Status }> = {
  ready: { tour: false },
  tour: { tour: true },
  away: { tour: false, patch: (s) => ({ ...s, gateway: { ...s.gateway, state: 'away', line: "Chat needs Zebra-Box, which isn't answering. It may be asleep or turned off.", last_answered: 'today at 9:41 AM' } }) },
  cap: { tour: false, patch: (s) => ({ ...s, budget: { ...(s.budget ?? {}), cap_line: "This month's $10 budget is used up." } }) },
};

test.describe('Ask about this screenshots (the gate for Tasks 9-11)', () => {
  test.skip(!TASK, 'set SHOTS_TASK to the task number');
  test('the panel on Eating out in four states, both sizes, light and dark', async ({ browser }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'one run is enough');
    test.setTimeout(600_000);
    const setup = await browser.newPage({ baseURL: `http://localhost:${DEMO_PORT}` });
    await loginAs(setup, 'alex');
    await chatOn(setup, 'ours');
    await setup.request.post('/api/b/ours/chat/seen', { data: {} });
    const me = (await (await setup.request.get('/api/auth/me')).json()) as { user: { id: number } };
    const { month } = (await (await setup.request.get('/api/b/ours/spending')).json()) as { month: string };
    await setup.close();
    // SHOTS_ONLY=ready|tour|away|cap narrows a re-shoot to one state.
    for (const [name, st] of Object.entries(STATES).filter(([n]) => !process.env.SHOTS_ONLY || n === process.env.SHOTS_ONLY)) {
      for (const theme of ['light', 'dark'] as const) {
        for (const [size, viewport] of SIZES) {
          const ctx = await browser.newContext({ viewport, baseURL: `http://localhost:${DEMO_PORT}` });
          await ctx.addInitScript(([t, id, tour]) => {
            localStorage.setItem('steward-theme', t);
            if (!tour) localStorage.setItem(`steward-ask-tour:${id}`, 'done');
          }, [theme, me.user.id, st.tour] as [string, number, boolean]);
          const page = await ctx.newPage();
          await loginAs(page, 'alex');
          const patch = st.patch;
          if (patch) {
            await page.route(/\/api\/b\/ours\/chat$/, async (route) => {
              const res = await route.fetch();
              await route.fulfill({ response: res, json: patch((await res.json()) as Status) });
            });
          }
          await page.goto(`/b/ours/spending/dining?month=${month}`);
          await page.getByRole('button', { name: 'Ask about Eating out' }).click();
          await page.getByRole('dialog', { name: 'Ask' }).locator('.ask-chip').waitFor({ timeout: 30_000 });
          await page.evaluate(() => document.fonts.ready);
          await animationsSettled(page);
          await page.screenshot({ path: `${OUT}/${name}-${size}-${theme}.png` });
          await ctx.close();
        }
      }
    }
  });

  test('the button on each surface, and the panel over a transaction on a phone, light and dark', async ({ browser }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop' || !process.env.SHOTS_SURFACES, 'set SHOTS_SURFACES=1 (Tasks 10-11)');
    test.setTimeout(600_000);
    const setup = await browser.newPage({ baseURL: `http://localhost:${DEMO_PORT}` });
    await loginAs(setup, 'alex');
    const { books } = (await (await setup.request.get('/api/books')).json()) as { books: { slug: string; name: string }[] };
    const mom = books.find((b) => b.name.startsWith('Margaret Ellis'))!.slug;
    for (const slug of ['ours', mom]) {
      await chatOn(setup, slug);
      await setup.request.post(`/api/b/${slug}/chat/seen`, { data: {} });
    }
    const { accounts } = (await (await setup.request.get('/api/b/ours/accounts')).json()) as { accounts: { id: number; type: string }[] };
    const checking = accounts.find((a) => a.type === 'checking')!.id;
    const { flags } = (await (await setup.request.get(`/api/b/${mom}/flags`)).json()) as { flags: { id: number }[] };
    const { month } = (await (await setup.request.get('/api/b/ours/spending')).json()) as { month: string };
    await setup.close();
    // [shot, address, the start of the button's name, Review's list view first (focus mode keeps Ask in its ⋯ menu)]
    const pages: [string, string, string, boolean][] = [
      ['account', `/b/ours/accounts/${checking}`, 'Ask about ', false],
      ['review', '/b/ours/review', 'Ask about ', true],
      ['ask-tab', `/b/ours/ask?about=category:dining:${month}`, 'Remove: About ', false],
      ['plan', '/b/ours/plan', 'Ask about the Plan', false],
      ['care', `/b/${mom}/care`, 'Ask about Care', false],
      ...(flags.length ? [['flag', `/b/${mom}/look-into/${flags[0].id}`, 'Ask about ', false] as [string, string, string, boolean]] : []),
    ];
    for (const theme of ['light', 'dark'] as const) {
      for (const [size, viewport] of SIZES) {
        const ctx = await browser.newContext({ viewport, baseURL: `http://localhost:${DEMO_PORT}` });
        await ctx.addInitScript((t) => { localStorage.setItem('steward-theme', t); }, theme);
        const page = await ctx.newPage();
        await loginAs(page, 'alex');
        for (const [name, path, button, list] of pages) {
          await page.goto(path);
          if (list) await page.locator('.rtop__view button').nth(1).click();       // Review's top bar: Focus | List
          await page.getByRole('button', { name: new RegExp(`^${button}`) }).first().waitFor({ timeout: 30_000 });
          await page.evaluate(() => document.fonts.ready);
          await animationsSettled(page);
          await page.screenshot({ path: `${OUT}/surface-${name}-${size}-${theme}.png`, fullPage: true });
        }
        if (size === '390x844') {               // the Ask sheet over the transaction's own sheet
          await page.goto(`/b/ours/accounts/${checking}`);
          await page.getByTestId('txn-row').first().click();
          const detail = page.getByRole('dialog').first();
          await detail.getByRole('button', { name: /^Ask about / }).click();
          await page.getByRole('dialog', { name: 'Ask' }).locator('.ask-chip').waitFor({ timeout: 30_000 });
          await animationsSettled(page);
          await page.screenshot({ path: `${OUT}/surface-stacked-${size}-${theme}.png` });
        }
        await ctx.close();
      }
    }
  });
});
