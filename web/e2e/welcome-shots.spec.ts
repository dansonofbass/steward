import { test, type Page } from '@playwright/test';
import { animationsSettled, loginAs, restoreVault, youMenu } from './fixtures';
import { DEMO_PORT, EMPTY_PORT } from './ports';

// The screenshot gate for the guided setup PR B tasks (6 to 11): set SHOTS_TASK to the task's number. Each task adds
// its states to BY_TASK; Task 11 finishes the map and runs the full set into shots/task-11.
declare const process: { env: Record<string, string | undefined> };
const TASK = process.env.SHOTS_TASK;
const SIZES = [['390x844', { width: 390, height: 844 }], ['1280x800', { width: 1280, height: 800 }]] as const;
const OUT = `../.superpowers/sdd/2026-11-09-steward-guided-setup-b/shots/task-${TASK}`;
const BY_TASK: Record<string, string[]> = { '6': ['help', 'you-menu'], '7': ['hello', 'money', 'sort', 'import-back'], '10': ['sample-home', 'sample-undo', 'sample-switcher'], '9': ['partner-hello', 'partner-switches', 'partner-work'], '8': ['extras', 'planted', 'invite-send-yourself', 'ready-cheer'],
  // Task 11: the whole gate. The first run's four steps are shot as robin on the empty household (unmarked, as a new
  // person sees them); the rest on the demo household as alex.
  '11': ['hello', 'money', 'sort', 'extras', 'planted', 'partner', 'sample'],
  // PR B's first-load additions moved to lazy chunks: Help's icon, and the invite and add-a-book sheets that now load on demand.
  bundle: ['you-menu', 'invite-send-yourself', 'add-book'] };
const FRESH = ['hello', 'money', 'sort', 'extras'];
const FRESH_AT: Record<string, [string, string]> = {
  hello: ['/b/ours/welcome', 'Steward'], money: ['/b/ours/welcome?step=money', 'Bring in your money'],
  sort: ['/b/ours/welcome?step=sort', 'Sort a few'], extras: ['/b/ours/welcome?step=extras', 'A few extras'],
};
// Task 7: alex's welcome is seen, so the first run is opened as a replay (?again=1).
const FIRST_RUN: Record<string, [string, string]> = {
  hello: ['/b/ours/welcome?again=1', 'Steward'], money: ['/b/ours/welcome?step=money&again=1', 'Bring in your money'], sort: ['/b/ours/welcome?step=sort&again=1', 'Sort a few'],
  extras: ['/b/ours/welcome?step=extras&again=1', 'A few extras'], planted: ['/b/ours/welcome?step=planted&again=1', 'Planted.'],
};

async function state(page: Page, name: string): Promise<boolean> {
  if (TASK === '11') {
    if (FRESH.includes(name)) {
      await page.goto(FRESH_AT[name][0]);
      await page.getByRole('heading', { name: FRESH_AT[name][1], level: 1 }).waitFor({ timeout: 15_000 });
      return true;
    }
    if (name === 'partner') {
      // alex manages a parent book, so its welcome plays as a replay (the real one, not a stub).
      await page.goto('/b/dad-seed-desktop/welcome?again=1');
      await page.getByRole('heading', { name: /^Welcome to /, level: 1 }).waitFor({ timeout: 15_000 });
      return true;
    }
    if (name === 'sample') name = 'sample-home';
  }
  if (FIRST_RUN[name]) {
    await page.goto(FIRST_RUN[name][0]);
    await page.getByRole('heading', { name: FIRST_RUN[name][1], level: 1 }).waitFor({ timeout: 15_000 });
    return true;
  }
  if (name.startsWith('partner-')) {
    // Task 9: alex is a household manager, so the welcome is stubbed as a partner's (inviter Pat) and opened as a replay.
    await page.route(/\/api\/(b\/[^/]+\/)?welcome(\?|$)/, async (route) => {
      if (route.request().method() !== 'GET') { await route.fallback(); return; }
      const body = await (await route.fetch()).json();
      await route.fulfill({ json: { ...body, kind: 'partner', seen: false, inviter: 'Pat' } });
    });
    await page.goto('/b/ours/welcome?again=1');
    await page.getByRole('heading', { name: /^Welcome to /, level: 1 }).waitFor({ timeout: 15_000 });
    if (name === 'partner-hello') return true;
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await page.getByRole('heading', { name: 'Your switches', level: 1 }).waitFor({ timeout: 15_000 });
    if (name === 'partner-switches') return true;
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await page.getByRole('heading', { name: 'Your name on your work', level: 1 }).waitFor({ timeout: 15_000 });
    return true;
  }
  if (name === 'import-back') {
    await page.goto('/b/ours/settings/import?from=welcome');
    await page.getByRole('link', { name: 'Back to setup' }).waitFor({ timeout: 15_000 });
    return true;
  }
  if (name === 'review-back') {
    await page.goto('/b/ours/review?from=welcome');
    await page.getByRole('heading', { name: 'Review', level: 1 }).waitFor({ timeout: 15_000 });
    return true;
  }
  if (name === 'invite-send-yourself') {
    // The demo install has email on, so the invite POST answers as an email-off install would (this shot only).
    await page.route('**/api/books/ours/members', async (route) => {
      if (route.request().method() !== 'POST') { await route.fallback(); return; }
      await route.fulfill({ status: 201, json: { member: { email: 'pat@example.com', role: 'viewer', status: 'Invited' }, invited: true,
        send_yourself: 'Hi Pat, I set up Steward for our money. Join us here: http://localhost:8441/invite?token=example' } });
    });
    await page.goto('/b/ours/settings/members');
    await page.getByRole('button', { name: 'Invite someone' }).click();
    await page.getByLabel('Email', { exact: true }).fill('pat@example.com');
    await page.getByRole('button', { name: 'Invite', exact: true }).click();
    await page.getByRole('button', { name: 'Copy' }).waitFor({ timeout: 15_000 });
    return true;
  }
  if (name === 'ready-cheer') {
    // The first answer needs one thing and the next needs none, so the page cheers as it would after Check again (this shot only).
    let need = 1;
    await page.route(/\/api\/(b\/[^/]+\/)?ready/, async (route) => {
      const body = await (await route.fetch()).json();
      if (need) {
        body.rows = body.rows.map((r: { key: string }) => r.key !== 'address' ? r : { ...r, status: 'needs', go: 'Check again', detail: 'Steward is at http://localhost:8441.',
          lines: [{ name: 'STEWARD_BASE_URL', line: 'STEWARD_BASE_URL=https://steward.example.ts.net', running: 'http://localhost:8441', note: null, where: 'steward' }] });
      }
      body.need = need;
      await route.fulfill({ json: body });
    });
    await page.goto('/settings/ready');
    await page.getByText('1 needs you').waitFor({ timeout: 15_000 });
    await page.getByRole('button', { name: /Secure address/ }).click();
    need = 0;
    await page.getByRole('button', { name: 'Check again', exact: true }).click();
    await page.locator('.ready__cheer').waitFor({ timeout: 15_000 });
    return true;
  }
  if (name.startsWith('sample-')) {
    // Task 10: alex makes a Sample, as Look around does, then opens it.
    await page.goto('/');
    const status = await page.evaluate(async () => (await fetch('/api/books/sample', { method: 'POST', credentials: 'same-origin' })).status);
    if (status !== 200 && status !== 201) throw new Error(`the Sample was refused: ${status}`);
    await page.goto('/b/sample');
    await page.getByRole('note').waitFor({ timeout: 15_000 });
    if (name === 'sample-home') return true;
    if (name === 'sample-undo') {
      await page.getByRole('button', { name: 'Remove the Sample' }).click();
      await page.getByRole('button', { name: 'Undo' }).waitFor({ timeout: 15_000 });
      return true;
    }
    await page.getByRole('button', { name: /^Switch book/ }).click();
    await page.getByText('Made-up money').waitFor({ timeout: 15_000 });
    return true;
  }
  if (name === 'add-book') {
    await page.goto('/b/ours/settings/books');
    await page.getByRole('button', { name: 'Add a book' }).click();
    await page.getByRole('dialog', { name: 'Add a book' }).waitFor({ timeout: 15_000 });
    return true;
  }
  if (name === 'help') {
    await page.goto('/you/help');
    await page.getByRole('heading', { name: 'Help', level: 1 }).waitFor({ timeout: 15_000 });
    return true;
  }
  if (name === 'you-menu') {
    await page.goto('/');
    await youMenu(page);
    await page.getByRole('link', { name: 'Help' }).waitFor({ timeout: 15_000 });
    return true;
  }
  return false;
}

test.describe('Guided setup PR B screenshots (the gate for Tasks 6 to 11)', () => {
  test.skip(!TASK || !BY_TASK[TASK], 'set SHOTS_TASK to a task number with states');
  test.beforeAll(async () => { await restoreVault(); });
  test('each state at both sizes, dark first, phone first', async ({ browser }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'one run is enough');
    test.setTimeout(600_000);
    for (const name of BY_TASK[TASK!]) {
      for (const theme of ['dark', 'light'] as const) {
        for (const [size, viewport] of SIZES) {
          const fresh = TASK === '11' && FRESH.includes(name);
          if (!fresh) await restoreVault();
          const ctx = await browser.newContext({ viewport, baseURL: `http://localhost:${fresh ? EMPTY_PORT.desktop : DEMO_PORT}` });
          await ctx.addInitScript((t) => { localStorage.setItem('steward-theme', t); }, theme);
          const page = await ctx.newPage();
          if (fresh) await loginAs(page, 'robin', 'pw-demo-robin-2026'); else await loginAs(page, 'alex');
          if (await state(page, name)) {
            await animationsSettled(page);
            await page.screenshot({ path: `${OUT}/${name}-${size}-${theme}.png` });
          }
          await ctx.close();
        }
      }
    }
  });
});
