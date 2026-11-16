import { expect, test } from '@playwright/test';
import { loginAs, restoreVault } from '../fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

// Sorting redesign, Performance 6: three sorts in a row with every celebration on, the CPU throttled 4x through CDP.
// No long task over 100 ms, a canvas was made, and none is left afterwards. (The reduced-motion test stays in ../celebrate.spec.ts.)
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


test('three sorts in a row with every celebration on: no long task over 100 ms, and the canvas goes', async ({ page }) => {
  test.setTimeout(60_000);
  // "Every celebration" includes the ding.
  await page.addInitScript(() => localStorage.setItem('steward-sound', 'on'));
  await page.goto('/review');
  const card = page.locator('[data-testid=focus-card][data-role=current]');
  await expect(card).toBeVisible();
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
  try {
    const start = await page.evaluate(() => performance.now());
    for (let i = 0; i < 3; i++) {
      const id = await card.getAttribute('data-id');
      const also = card.getByRole('checkbox', { name: /^Also the / });     // the box test needs the matching rows
      if (await also.count()) await also.uncheck();
      await card.locator('.chips button:not(.chip--more)').first().click();
      await expect(card).not.toHaveAttribute('data-id', id!);
    }
    // Every effect ends within 1.6 s of its start; then the canvas is gone.
    await expect(page.locator('[data-testid=focus-card][data-role=leaving]')).toHaveCount(0, { timeout: 15_000 });
    await expect(page.locator('canvas.cel-canvas')).toHaveCount(0, { timeout: 5_000 });
    const s = await page.evaluate(seen);
    const long = s.long.filter((e) => e.start >= start);
    console.log(`PERF celebrate: ${long.length} long tasks after the first tap (${long.map((e) => e.duration.toFixed(0)).join(', ') || 'none'}); `
      + `${s.canvases} canvas made`);
    expect(s.canvases).toBeGreaterThan(0);
    expect(long.filter((e) => e.duration > 100)).toEqual([]);
  } finally {
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: 1 });
  }
});
