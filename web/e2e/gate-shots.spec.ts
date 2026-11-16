import { expect, test, type Page } from '@playwright/test';
import { animationsSettled, chatOn, DEMO, GATEWAY, restoreVault } from './fixtures';
import { loaded, open, origin, signIn, THEMES } from './open-screen';
import { DEMO_PORT } from './ports';
import { addDemoRecords, SCREENS } from './screens';

declare const process: { env: Record<string, string | undefined> };

// The release gate's screenshots (plan 2026-11-09, Tasks 9, 10 and 14), kept for later releases. Every screen in
// screens.ts, in each project's dark and light (phone-dark, phone-light, desktop-dark, desktop-light): a full-page PNG
// and the page's accessibility snapshot. On the phone in dark only, six moments and a keyboard trace. Files go to
// web/e2e/screenshots-gate/ (gitignored). Runs only with GATE_SHOTS=1. GATE_ONLY=name,name runs only those screens,
// and `moments` and `keyboard` name the other two parts.

const OUT = 'e2e/screenshots-gate';
const DEMO_AT = `http://localhost:${DEMO_PORT}`;
const ONLY = process.env.GATE_ONLY?.split(',').map((s) => s.trim()).filter(Boolean);
const PARTS = new Set([...SCREENS.map((s) => s.name), 'moments', 'keyboard']);
const unknown = (ONLY ?? []).filter((n) => !PARTS.has(n));
if (process.env.GATE_SHOTS && unknown.length) throw new Error(`GATE_ONLY names no screen or part: ${unknown.join(', ')}`);
const wanted = (part: string) => !ONLY || ONLY.includes(part);

/** The event services/simplefin/sync.py logs for a bank whose SimpleFIN sign-in lapsed (the demo seeds two). */
const SYNC_FAILED = /needs you to sign in again at SimpleFIN/;

test.skip(!process.env.GATE_SHOTS, 'set GATE_SHOTS=1 to take the release gate screenshots');

test.beforeAll(async ({ playwright }) => {
  await restoreVault();
  const request = await playwright.request.newContext({ baseURL: DEMO_AT });
  expect((await request.post('/api/auth/login', { data: { username: 'alex', password: DEMO.alex, device_label: 'e2e' } })).ok()).toBeTruthy();
  await addDemoRecords(request);
  await request.post(`${GATEWAY}/__e2e/reset`);
  await request.dispose();
});

type Fs = { mkdirSync(path: string, options: { recursive: true }): void; writeFileSync(path: string, data: string): void };
const NODE_FS: string = 'node:fs';   // imported at run time: the e2e tsconfig carries no Node types

async function writeText(path: string, text: string) {
  const fs = (await import(NODE_FS)) as Fs;
  fs.mkdirSync(path.slice(0, path.lastIndexOf('/')), { recursive: true });
  fs.writeFileSync(path, text.endsWith('\n') ? text : `${text}\n`);
}

for (const s of SCREENS) {
  test(`${s.name}, dark and light`, async ({ page }, info) => {
    test.skip(!wanted(s.name), 'not in GATE_ONLY');
    const at = origin(s, info.project.name);
    if (s.signedIn) await signIn(page, at);
    await page.goto(`${at}/api/health`);   // an origin to write the theme setting on
    for (const [theme, phase] of THEMES) {
      await open(page, `${at}${s.url}`, theme, phase);
      await loaded(page, s);
      const mode = `${info.project.name}-${theme}`;
      await page.screenshot({ path: `${OUT}/${mode}/${s.name}.png`, fullPage: true });
      await writeText(`${OUT}/${mode}/${s.name}.aria.txt`, await page.locator('body').ariaSnapshot());
    }
  });
}

/** Signed in as alex on the demo, in dark, at url. */
async function darkAt(page: Page, url: string) {
  await signIn(page, DEMO_AT);
  await page.goto(`${DEMO_AT}/api/health`);
  await open(page, `${DEMO_AT}${url}`, 'dark', 'night');
}

async function shoot(page: Page, name: string) {
  await page.evaluate(async () => { await document.fonts.ready; });
  await animationsSettled(page);
  await page.screenshot({ path: `${OUT}/phone-dark/moment-${name}.png` });
}

/** Sorts the Review card on screen with its first category, leaving the rows like it for later. */
async function sortOne(page: Page) {
  const card = page.locator('[data-testid=focus-card][data-role=current]');
  const id = await card.getAttribute('data-id');
  const also = card.getByRole('checkbox', { name: /^Also the / });
  if (await also.count()) await also.uncheck();
  await card.locator('.chips button:not(.chip--more)').first().click();
  await expect(page.locator('.undo-toast')).toContainText('SORTED');
  await expect(card).not.toHaveAttribute('data-id', id!);
}

/** A category rule, made the way a sort makes one, so Settings, Category rules has one to remove. */
async function aRule(page: Page) {
  const review = (await (await page.request.get(`${DEMO_AT}/api/b/ours/review`)).json()) as { uncategorized: { id: number }[] };
  const last = review.uncategorized.at(-1);
  if (!last) throw new Error('the demo Review queue is empty');
  expect((await page.request.patch(`${DEMO_AT}/api/b/ours/transactions/${last.id}`, { data: { category: 'dining' } })).ok()).toBeTruthy();
}

test.describe('moments, phone dark', () => {
  test.beforeEach(({}, info) => {
    test.skip(info.project.name !== 'phone' || !wanted('moments'), 'the moments are taken once, on the phone');
  });

  test('an Undo toast after a Review sort', async ({ page }) => {
    await darkAt(page, '/b/ours/review');
    await sortOne(page);
    await shoot(page, 'undo-toast');
  });

  test('a celebration under reduced motion', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await darkAt(page, '/b/ours/review');
    await sortOne(page);
    await shoot(page, 'celebration-reduced-motion');
  });

  test('an open delete confirm', async ({ page }) => {
    await darkAt(page, '/b/ours/settings/rules');
    await aRule(page);
    await page.reload();
    await page.getByRole('button', { name: /^Remove rule for / }).first().click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await shoot(page, 'delete-confirm');
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });

  test('a red month on Home (its numbers routed)', async ({ page }) => {
    await page.route(/\/api\/b\/ours\/home(\?.*)?$/, async (route) => {
      const res = await route.fetch();
      const h = (await res.json()) as { flow: Record<string, unknown> };
      await route.fulfill({ response: res, json: { ...h, flow: { ...h.flow, in_cents: 210_000, out_cents: 251_000, net_cents: -41_000, payday: { day: 15 } } } });
    });
    await darkAt(page, '/b/ours');
    await page.getByTestId('verdict').and(page.locator('[data-ready=true]')).waitFor();
    await expect(page.getByText(/in the red so far this month/)).toBeVisible();
    await shoot(page, 'red-month-routed');
  });

  test('a failed sync', async ({ page }) => {
    // Home's For you, with the demo's seeded sync events for banks whose SimpleFIN sign-in lapsed: nothing routed.
    await darkAt(page, '/b/ours');
    const notice = page.getByText(SYNC_FAILED).first();
    await notice.scrollIntoViewIfNeeded();
    await expect(notice).toBeVisible();
    await shoot(page, 'sync-failed');
  });

  test('the Ask composer showing What Claude will see', async ({ page }) => {
    await signIn(page, DEMO_AT);
    await chatOn(page, 'ours');
    await page.goto(`${DEMO_AT}/api/health`);
    await open(page, `${DEMO_AT}/b/ours/ask`, 'dark', 'night');
    const start = page.getByRole('button', { name: 'Start' });
    const box = page.getByLabel('Your question');
    await expect(start.or(box).first()).toBeVisible();
    if (await start.isVisible()) await start.click();
    await box.fill('Can Sam pay Bright Smile Ortho $6,400 from savings?');
    await expect(page.locator('.willsend__text').first()).not.toHaveText('…');
    await expect(page.locator('.tok').first()).toBeVisible();
    await shoot(page, 'ask-will-see');
    await chatOn(page, 'ours', false);
  });
});

/** The focused element as the accessibility tree names it: its role and name. */
async function focused(page: Page): Promise<string> {
  const f = page.locator(':focus');
  if ((await f.count()) === 0) return '(the page itself)';
  return (await f.first().ariaSnapshot()).split('\n')[0].replace(/^- /, '').replace(/:$/, '');
}

test('a keyboard trace through sign-in, a Review sort, an Undo and a delete confirm', async ({ page }, info) => {
  test.skip(info.project.name !== 'phone' || !wanted('keyboard'), 'the trace is taken once, on the phone');
  test.setTimeout(120_000);
  const trace: string[] = ['# The focused element (role and name) after each key, phone, dark.'];
  /** Tab until the focused element matches want (its role and name, or a CSS selector), keeping each stop. */
  async function tabTo(label: string, want: RegExp | string, most = 80) {
    trace.push('', `## ${label}`);
    for (let i = 0; i < most; i++) {
      await page.keyboard.press('Tab');
      const now = await focused(page);
      trace.push(`Tab -> ${now}`);
      const hit = typeof want === 'string' ? await page.evaluate((sel) => !!document.activeElement?.matches(sel), want) : want.test(now);
      if (hit) return;
    }
    throw new Error(`${label}: ${most} Tabs never reached ${String(want)}`);
  }
  async function press(key: string) {
    await page.keyboard.press(key);
    trace.push(`${key} -> ${await focused(page)}`);
  }
  try {
    await page.addInitScript(() => { localStorage.setItem('steward-swipe-demo', 'done'); });
    await page.goto(`${DEMO_AT}/api/health`);
    await open(page, `${DEMO_AT}/login`, 'dark', 'night');
    await tabTo('Sign in: the username', /^textbox "Username"/);
    await page.keyboard.type('alex');
    await tabTo('the password', /^textbox "Password"/);
    await page.keyboard.type(DEMO.alex);
    await tabTo('the Sign in button', /^button "Sign in"$/);
    await press('Enter');
    await expect(page).not.toHaveURL(/\/login/);

    await page.goto(`${DEMO_AT}/b/ours/review`);
    const card = page.locator('[data-testid=focus-card][data-role=current]');
    const id = await card.getAttribute('data-id');
    await tabTo('Review: a category on the card', '[data-testid=focus-card][data-role=current] .chips button:not(.chip--more)');
    await press('Enter');
    await expect(page.locator('.undo-toast')).toContainText('SORTED');
    await expect(card).not.toHaveAttribute('data-id', id!);
    await tabTo('Undo', /^button "Undo/);
    await press('Enter');
    await expect(card).toHaveAttribute('data-id', id!);

    await aRule(page);
    trace.push('', '(A category rule made through the API, so there is one to remove.)');
    await page.goto(`${DEMO_AT}/b/ours/settings/rules`);
    await tabTo('Delete: a rule\'s Remove', /^button "Remove rule for /);
    await press('Enter');
    await expect(page.getByRole('dialog')).toBeVisible();
    await tabTo('the sheet\'s Remove', /^button "Remove"$/);
    await press('Enter');
    await expect(page.getByRole('dialog')).toHaveCount(0);
  } finally {
    await writeText(`${OUT}/keyboard.txt`, trace.join('\n'));
  }
});
