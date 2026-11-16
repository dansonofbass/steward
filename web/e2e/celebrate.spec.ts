import { expect, test } from '@playwright/test';
import { loginAs, restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

// Sorting redesign, Performance 6: reduced motion loads no celebration. (The three-sorts timing budget is in perf/celebrate.spec.ts.)
type Seen = { long: { start: number; duration: number }[]; canvases: number };
const seen = () => (window as unknown as { __seen: Seen }).__seen;

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const s: Seen = { long: [], canvases: 0 };
    (window as unknown as { __seen: Seen }).__seen = s;
    new PerformanceObserver((list) => { for (const e of list.getEntries()) s.long.push({ start: e.startTime, duration: e.duration }); })
      .observe({ type: 'longtask', buffered: true });
    new MutationObserver((records) => {
      for (const r of records) for (const n of r.addedNodes) if (n instanceof HTMLCanvasElement && n.classList.contains('cel-canvas')) s.canvases++;
    }).observe(document, { childList: true, subtree: true });
  });
  await loginAs(page, 'spouse');
});

test('with reduced motion a sort just swaps the card, the toast says so, and no celebration loads', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const asked: string[] = [];
  page.on('request', (r) => { if (/\/assets\/celebrate-/.test(r.url())) asked.push(r.url()); });
  await page.goto('/review');
  const card = page.locator('[data-testid=focus-card][data-role=current]');
  const id = await card.getAttribute('data-id');
  // Leave the household's matching rows for the Review spec's box test.
  const also = card.getByRole('checkbox', { name: /^Also the / });
  if (await also.count()) await also.uncheck();
  await card.locator('.chips button:not(.chip--more)').first().click();
  await expect(page.locator('.undo-toast')).toContainText('SORTED');
  await expect(card).not.toHaveAttribute('data-id', id!);
  await expect(page.locator('[data-testid=focus-card][data-role=leaving]')).toHaveCount(0);
  expect(asked).toEqual([]);
  expect((await page.evaluate(seen)).canvases).toBe(0);
});
