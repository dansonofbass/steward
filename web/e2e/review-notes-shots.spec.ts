import { expect, test, type Page } from '@playwright/test';
import { listView, loginAs, restoreVault } from './fixtures';
import { DEMO_PORT } from './ports';

// Review cards show their notes: the screenshot gate. The first queue card with two notes from two people (Sam's, then
// Alex's saved from the card, toast up), in list and focus, at 1280x800 and 390x844, light and dark, viewport only.
// SHOTS_TASK=review-notes runs it; without it it skips, so the full e2e run passes over it.
declare const process: { env: Record<string, string | undefined> };
const RUN = process.env.SHOTS_TASK === 'review-notes';
// Playwright runs from web/ and creates the folder when it saves.
const OUT = '../.superpowers/sdd/review-notes/shots';
const SIZES = [['1280x800', { width: 1280, height: 800 }, false], ['390x844', { width: 390, height: 844 }, true]] as const;
const THEMES = ['dark', 'light'] as const;
const MINE = 'Asked Sam about this one';

test.beforeAll(async () => { await restoreVault(); });

/** Alex saves a note from the card, then the shot waits for both lines and the toast, with fonts and animations done. */
async function noteFrom(page: Page, mode: 'list' | 'focus') {
  const card = mode === 'list'
    ? page.getByTestId('review-card').first()
    : page.locator('[data-testid=focus-card][data-role=current]');
  if (mode === 'list') {
    await card.getByRole('button', { name: 'Note' }).click();
  } else {
    await card.getByRole('button', { name: 'More actions' }).click();
    await page.getByRole('menuitem', { name: 'Add note' }).click();
  }
  await card.getByTestId('note-form').getByLabel('Note').fill(MINE);
  await card.getByTestId('note-form').getByRole('button', { name: 'Save' }).click();
  await expect(card.locator('.notes__list li')).toHaveCount(2);
  await page.locator('.undo-toast').filter({ hasText: /^Saved/ }).waitFor();
  if (mode === 'list') await card.evaluate((el) => { window.scrollBy(0, el.getBoundingClientRect().top - 72); });   // the card's top in view
  await page.evaluate(() => Promise.all([document.fonts.ready, ...document.getAnimations().map((a) => a.finished.catch(() => null))]));
  return card;
}

test.describe('review notes: screenshots', () => {
  test.skip(!RUN, 'set SHOTS_TASK=review-notes');
  test('a card with two notes, list and focus, both sizes, light and dark', async ({ browser }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'one run is enough');
    test.setTimeout(600_000);
    // Sam's note on the first card in the queue, once; Alex's comes from the card in each shot and is removed after.
    const sam = await browser.newContext({ baseURL: `http://localhost:${DEMO_PORT}` });
    const sp = await sam.newPage();
    await loginAs(sp, 'spouse');
    const id = ((await (await sp.request.get('/api/b/ours/review')).json()) as { uncategorized: { id: number }[] }).uncategorized[0].id;
    const made = await sp.request.post(`/api/b/ours/transactions/${id}/notes`, { data: { body: 'Paid my half in cash' } });
    expect(made.ok()).toBeTruthy();
    for (const mode of ['list', 'focus'] as const) {
      for (const theme of THEMES) {
        for (const [size, viewport, touch] of SIZES) {
          const ctx = await browser.newContext({ viewport, hasTouch: touch, baseURL: `http://localhost:${DEMO_PORT}` });
          await ctx.addInitScript((t) => { localStorage.setItem('steward-theme', t); localStorage.setItem('steward-swipe-demo', 'nudged'); }, theme);
          const page = await ctx.newPage();
          await loginAs(page, 'alex');
          await page.goto('/review');
          await page.getByTestId(mode === 'list' ? 'review-top' : 'focus-card').first().waitFor();
          if (mode === 'list') await listView(page);
          const card = await noteFrom(page, mode);
          expect(await card.getAttribute('data-id')).toBe(String(id));
          await page.screenshot({ path: `${OUT}/${mode}-${size}-${theme}.png` });
          // Mid-remove: Alex's line gone at once, "Removed · Undo" up, Sam's line still there. That leaves Sam's alone.
          await card.locator('.notes__list li').filter({ hasText: MINE }).getByRole('button', { name: /^Remove note from / }).click();
          await expect(card.locator('.notes__list li')).toHaveCount(1);
          await page.locator('.undo-toast').filter({ hasText: /^Removed/ }).waitFor();
          await page.evaluate(() => Promise.all([document.fonts.ready, ...document.getAnimations().map((a) => a.finished.catch(() => null))]));
          await page.screenshot({ path: `${OUT}/remove-${mode}-${size}-${theme}.png` });
          await ctx.close();
        }
      }
    }
    const left = (await (await sp.request.get(`/api/b/ours/transactions/${id}/notes`)).json()) as { notes: { id: number }[] };
    for (const n of left.notes) await sp.request.delete(`/api/b/ours/transactions/${id}/notes/${n.id}`);
    await sam.close();
  });
});
