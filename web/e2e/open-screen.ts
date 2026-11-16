import { expect, type Page } from '@playwright/test';
import { animationsSettled, DEMO } from './fixtures';
import { DEMO_PORT, EMPTY_PORT } from './ports';
import type { Screen } from './screens';

// Opening one of screens.ts's screens, for the axe check (axe.spec.ts) and the release gate's screenshots
// (gate-shots.spec.ts). Not in screens.ts: Vitest reads that file, and this one imports Playwright.

/** The app's theme setting and the phase it puts on <html>. */
export const THEMES = [['dark', 'night'], ['light', 'day']] as const;
/** What a page that didn't open shows: React Router's own error page for an unknown address (routes.tsx has no
 *  catch-all), and the API's answer for an id that isn't there. */
export const NOT_FOUND = ['Unexpected Application Error!', '404 Not Found', 'Not found.'];

/** The server a screen lives on: the demo household, or this project's empty household. */
export const origin = (s: Screen, project: string) =>
  `http://localhost:${s.server === 'empty' ? EMPTY_PORT[project as keyof typeof EMPTY_PORT] : DEMO_PORT}`;

/** Signs in as alex on the screen's server (on the empty household only alex, who has seen the welcome: kit's and
 *  robin's welcome marks are welcome.spec's) and keeps the first-use tips out of the way. */
export async function signIn(page: Page, at: string) {
  const r = await page.request.post(`${at}/api/auth/login`, { data: { username: 'alex', password: DEMO.alex, device_label: 'e2e' } });
  expect(r.ok()).toBeTruthy();
  const me = (await (await page.request.get(`${at}/api/auth/me`)).json()) as { user: { id: number } };
  await page.addInitScript((id) => {
    localStorage.setItem(`steward-ask-tour:${id}`, 'done');
    localStorage.setItem('steward-swipe-demo', 'done');
  }, me.user.id);
}

/** Open, in the theme asked for: the app follows its own setting, not the device's (spec 2.6), so the setting is
 *  written and the page loaded again, and the phase on <html> confirms it. */
export async function open(page: Page, url: string, theme: string, phase: string) {
  await page.evaluate((t) => localStorage.setItem('steward-theme', t), theme);
  await page.goto(url);
  await expect(page.locator('html')).toHaveAttribute('data-phase', phase);
}

/** Loaded: the screen's heading on screen, nothing still loading, nothing moving, and no not-found page. */
export async function loaded(page: Page, s: Screen) {
  const heading = page.getByRole('heading', { name: s.heading, exact: typeof s.heading === 'string' }).first();
  try {
    await expect(heading).toBeVisible();
  } catch {
    throw new Error(`${s.name}: no heading ${String(s.heading)} at ${page.url()}; headings: ${JSON.stringify(await page.getByRole('heading').allInnerTexts())}`);
  }
  // The design page shows a skeleton and a busy button on purpose, as samples.
  await page.waitForFunction(() => ![...document.querySelectorAll('.skeleton, [aria-busy="true"]')].some((e) => !e.closest('.design')));
  for (const text of NOT_FOUND) await expect(page.getByText(text, { exact: true })).toHaveCount(0);
  await page.evaluate(async () => { await document.fonts.ready; });
  await animationsSettled(page);
}
