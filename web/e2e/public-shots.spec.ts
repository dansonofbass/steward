import { test, type Page } from '@playwright/test';
import { animationsSettled, chatOn, loginAs, restoreVault, tab } from './fixtures';
import { DEMO_PORT, EMPTY_PORT } from './ports';

// The screenshot gate for the public docs tasks: set SHOTS_TASK to the task's number (8 now; the README and docs tasks add theirs).
declare const process: { env: Record<string, string | undefined> };
const TASK = process.env.SHOTS_TASK;
const SIZES = [['390x844', { width: 390, height: 844 }], ['1280x800', { width: 1280, height: 800 }]] as const;
const OUT = `../.superpowers/sdd/2026-11-09-steward-public-docs/shots/task-${TASK}`;
const BY_TASK: Record<string, string[]> = { '8': ['about', 'plan-foot', 'taxes-foot', 'business-foot'] };

const REPORT = {
  year: 2026, this_year: 2026, through: '2026-10-13', type: 'sole_prop', income_cents: 500000, expenses_cents: 139251, profit_cents: 360749,
  lines: [
    { key: 'income', number: '1', label: 'Income', spent_cents: 500000, counts_cents: 500000, count: 2, note: null },
    { key: 'software', number: '27b', label: 'Software', spent_cents: 2000, counts_cents: 2000, count: 2, note: null },
  ],
  range: { year: 2026, ytd_cents: 360749, low_cents: 360749, high_cents: 360749, mid_cents: 360749, entered: false,
    cash_ytd_cents: 360749, cash_low_cents: 360749, cash_high_cents: 360749, cash_mid_cents: 360749, ask_expect: false },
  left_out: 0, using_note: null, home_office_limited: false,
};

/** Opens the screen and, for a foot shot, scrolls to the bottom so the not-advice line is in view. */
async function state(page: Page, name: string): Promise<void> {
  const route = { about: '/you/about', 'plan-foot': '/plan', 'taxes-foot': '/taxes', 'business-foot': '/b/ours/business' }[name]!;
  // The demo household has no business turned on, so the Business shot answers with a made-up report.
  if (name === 'business-foot') await page.route('**/api/b/ours/business*', (r) => r.fulfill({ json: REPORT }));
  await page.goto(route);
  await page.waitForLoadState('networkidle');
  await page.getByText(name === 'about' ? 'Free software under the GNU AGPL' : 'Estimates, not financial or tax advice.').first().waitFor({ timeout: 15_000 });
  if (name.endsWith('-foot')) await page.evaluate(() => { document.querySelectorAll('*').forEach((e) => { e.scrollTop = e.scrollHeight; }); window.scrollTo(0, document.body.scrollHeight); });
}

// SHOTS_TASK=readme: the curated shots the public docs show (plan D9), written to docs/screenshots/<name>.png, viewport only.
// Phone shots are 390x844 at scale 2, dark; desktop shots are 1280x800, light. Everything comes from the e2e servers'
// made-up vaults; a route patch only picks which state a row shows. SHOTS_ONLY=name,name narrows a run.
const README_OUT = '../docs/screenshots';
const ONLY = process.env.SHOTS_ONLY ? new Set(process.env.SHOTS_ONLY.split(',')) : null;
const PHONE = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, theme: 'dark' } as const;
const DESKTOP = { viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1, theme: 'light' } as const;
const README_SHOTS: [string, typeof PHONE | typeof DESKTOP][] = [
  ['signin', PHONE], ['first-run', PHONE], ['home', PHONE], ['review', PHONE], ['ask', PHONE], ['sent', PHONE],
  ['ready', DESKTOP], ['plan', DESKTOP], ['access', DESKTOP], ['email', DESKTOP], ['backups', DESKTOP], ['bank-link', DESKTOP],
  ['gateway-pair', DESKTOP],
];

async function readmeState(page: Page, name: string): Promise<void> {
  const ready = async () => {
    await page.goto('/settings/ready');
    await page.getByRole('heading', { name: 'Get Steward ready', level: 2 }).waitFor();
    await page.getByTestId('ready-row').first().waitFor();
  };
  if (name === 'signin') {
    await page.goto('/');
    await page.locator('input[type=password]').waitFor({ timeout: 15_000 });
  } else if (name === 'first-run') {
    await page.goto('/');
    await page.getByRole('button', { name: 'Set up my household' }).waitFor({ timeout: 15_000 });
  } else if (name === 'home') {
    await page.goto('/');
    await page.getByRole('heading', { level: 1 }).first().waitFor({ timeout: 15_000 });
    // The Business sign and the month strip load after the summary; shoot once no skeleton is left in the vital
    // signs and the strip (its own chunk) is drawn.
    await page.getByTestId('signs').waitFor();
    await page.getByTestId('signs').locator('.skeleton').waitFor({ state: 'detached' });
    await page.getByTestId('flow-strip').waitFor();
  } else if (name === 'review') {
    await page.goto('/review');
    await page.locator('[data-testid=focus-card], .review__done').first().waitFor({ timeout: 15_000 });
  } else if (name === 'ask') {
    const { month } = (await (await page.request.get('/api/b/ours/spending')).json()) as { month: string };
    await page.goto(`/b/ours/spending/dining?month=${month}`);
    await page.getByRole('button', { name: 'Ask about Eating out' }).click();
    await page.getByRole('dialog', { name: 'Ask' }).locator('.ask-chip').waitFor({ timeout: 30_000 });
  } else if (name === 'sent') {
    // One real question through the fake gateway, so the log has something to show (made-up answer, made-up household).
    await page.goto('/b/ours');
    await tab(page, 'Ask').click();
    await page.getByLabel('Your question').fill('Are we spending more on dining than last year?');
    await page.locator('.willsend__text').first().waitFor();
    await page.getByRole('button', { name: 'Send' }).last().click();
    await page.locator('.amsg__meta').last().waitFor({ timeout: 30_000 });
    await page.goto('/b/ours/settings/chat/sent');
    await page.getByRole('button', { name: /Question/ }).first().waitFor({ timeout: 15_000 });
  } else if (name === 'ready') {
    await ready();
  } else if (name === 'plan') {
    await page.goto('/plan');
    await page.getByRole('heading', { level: 1 }).first().waitFor({ timeout: 15_000 });
  } else if (name === 'access') {
    // The demo server's address is already fine, so this shot shows the state that needs the line (this shot only).
    await page.route('**/api/b/ours/ready*', async (route) => {
      const body = await (await route.fetch()).json();
      body.rows = body.rows.map((r: { key: string }) => r.key !== 'address' ? r : { ...r, status: 'needs', go: 'Check again', detail: 'Steward is at http://localhost:8441.',
        lines: [{ name: 'STEWARD_BASE_URL', line: 'STEWARD_BASE_URL=https://steward.example.ts.net', running: 'http://localhost:8441', note: null, where: 'steward' }] });
      body.need = 1;
      await route.fulfill({ json: body });
    });
    await ready();
    await page.getByRole('button', { name: /Secure address/ }).click();
    await page.getByText('STEWARD_BASE_URL=https://steward.example.ts.net').first().waitFor();
  } else if (name === 'email') {
    await ready();
    await page.getByRole('button', { name: /^Email/ }).click();
    await page.getByLabel('Host').waitFor();
  } else if (name === 'backups') {
    // The e2e server keeps its copies in a temporary folder; the screen shows the folder the compose file gives a real install.
    await page.route('**/api/install/settings', async (route) => {
      const body = await (await route.fetch()).json();
      body.backups = { ...body.backups, dir: '/data/backups' };
      await route.fulfill({ json: body });
    });
    await ready();
    await page.getByRole('button', { name: /^Backups/ }).click();
    await page.getByLabel('Ping URL').waitFor();
  } else if (name === 'bank-link') {
    await page.goto('/settings/banks');
    await page.getByLabel('Setup token').waitFor({ timeout: 15_000 });
  } else if (name === 'gateway-pair') {
    // alex is paired in the demo vault, so this shot shows the unpaired state (this shot only; the vault is never unpaired).
    await page.route('**/api/b/ours/chat', async (route) => {
      const body = await (await route.fetch()).json();
      body.gateway = { ...body.gateway, state: 'not_set_up', line: 'Not paired.', paired: false, url_set: true };
      await route.fulfill({ json: body });
    });
    await page.goto('/settings/chat');
    await page.getByLabel('Code', { exact: true }).waitFor({ timeout: 15_000 });
  } else {
    throw new Error(`no readme shot called ${name}`);
  }
}

test.describe('Public docs screenshots (the curated set, SHOTS_TASK=readme)', () => {
  test.skip(TASK !== 'readme', 'set SHOTS_TASK to readme');
  test.beforeAll(async () => { await restoreVault(); });
  test('each shot, written to docs/screenshots', async ({ browser }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'one run is enough');
    test.setTimeout(600_000);
    for (const [name, look] of README_SHOTS.filter(([n]) => (ONLY ? ONLY.has(n) : true))) {
      await restoreVault();
      // The first run is on the empty household, as a new person sees it; the sign-in page needs no one signed in.
      const port = name === 'first-run' ? EMPTY_PORT.desktop : DEMO_PORT;
      const ctx = await browser.newContext({ viewport: look.viewport, deviceScaleFactor: look.deviceScaleFactor, baseURL: `http://localhost:${port}` });
      await ctx.addInitScript((t) => { localStorage.setItem('steward-theme', t); }, look.theme);
      const page = await ctx.newPage();
      if (name === 'first-run') await loginAs(page, 'kit', 'pw-demo-kit-2026');
      else if (name !== 'signin') {
        await loginAs(page, 'alex');
        if (name === 'ask' || name === 'sent') {
          await chatOn(page, 'ours');
          await page.request.post('/api/b/ours/chat/seen', { data: {} });
          const me = (await (await page.request.get('/api/auth/me')).json()) as { user: { id: number } };
          await page.addInitScript((id) => { localStorage.setItem(`steward-ask-tour:${id}`, 'done'); }, me.user.id);
        }
      }
      await readmeState(page, name);
      await page.evaluate(() => document.fonts.ready);
      await animationsSettled(page);
      await page.screenshot({ path: `${README_OUT}/${name}.png` });
      await ctx.close();
    }
  });
});

test.describe('Public docs screenshots (the gate for Task 8)', () => {
  test.skip(!TASK || !BY_TASK[TASK], 'set SHOTS_TASK to 8');
  test.beforeAll(async () => { await restoreVault(); });
  test('each screen at both sizes, dark first, phone first', async ({ browser }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'one run is enough');
    test.setTimeout(600_000);
    for (const name of BY_TASK[TASK!]) {
      for (const theme of ['dark', 'light'] as const) {
        for (const [size, viewport] of SIZES) {
          await restoreVault();
          const ctx = await browser.newContext({ viewport, baseURL: `http://localhost:${DEMO_PORT}` });
          await ctx.addInitScript((t) => { localStorage.setItem('steward-theme', t); }, theme);
          const page = await ctx.newPage();
          await loginAs(page, 'alex');
          await state(page, name);
          await animationsSettled(page);
          await page.screenshot({ path: `${OUT}/${name}-${size}-${theme}.png` });
          await ctx.close();
        }
      }
    }
  });
});
