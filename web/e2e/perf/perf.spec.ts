import { expect, test } from '@playwright/test';
import { CHAT_PW, chatOn, listView, loginAs, restoreVault } from '../fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

// Spec section 9: Home interactive on a phone over Tailscale < 1.5 s; review action round trip < 150 ms.
// The perf project (a phone); the CPU is throttled 4x and the network shaped like a tailnet hop (30 ms RTT, 25/10 Mbps).

const RUNS = 5;
const median = (xs: number[]) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)];

// Issue #24: layout shift on Home, the session-window CLS of web.dev/cls (gaps under 1 s, windows under 5 s), counted
// from the first paint until the strip, Since and the fonts have all landed. Budget 0.1, the "good" line.
const CLS_BUDGET = 0.1;
const watchLayoutShift = () => {
  const w = window as unknown as { __cls: number };
  w.__cls = 0;
  let windowValue = 0;
  let first = 0;
  let last = 0;
  new PerformanceObserver((list) => {
    for (const e of list.getEntries() as (PerformanceEntry & { value: number; hadRecentInput: boolean })[]) {
      if (e.hadRecentInput) continue;
      if (windowValue && e.startTime - last < 1000 && e.startTime - first < 5000) windowValue += e.value;
      else { windowValue = e.value; first = e.startTime; }
      last = e.startTime;
      w.__cls = Math.max(w.__cls, windowValue);
    }
  }).observe({ type: 'layout-shift', buffered: true });
};

test('Home is interactive under 1.5 s on a throttled phone, and nothing on it moves', async ({ page }) => {
  await loginAs(page, 'alex');
  await page.addInitScript(watchLayoutShift);
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 30, downloadThroughput: (25 * 1024 * 1024) / 8, uploadThroughput: (10 * 1024 * 1024) / 8 });
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: true });
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
  const times: number[] = [];
  const shifts: number[] = [];
  for (let i = 0; i < RUNS; i++) {
    await page.goto('about:blank');
    await page.goto('/', { waitUntil: 'commit' });
    await page.getByTestId('verdict').and(page.locator('[data-ready=true]')).waitFor();
    await page.waitForFunction(() => performance.getEntriesByName('home-ready').length > 0);
    // Home re-marks on remount; the first entry after a fresh navigation is the load we want.
    times.push(await page.evaluate(() => performance.getEntriesByName('home-ready')[0].startTime));
    await page.getByTestId('flow-strip').waitFor();
    await page.evaluate(() => document.fonts.ready);
    // The shifts are reported with the next frame; two frames on, every one from the arrivals above is counted.
    shifts.push(await page.evaluate(() => new Promise<number>((done) => {
      requestAnimationFrame(() => requestAnimationFrame(() => done((window as unknown as { __cls: number }).__cls)));
    })));
  }
  console.log(`PERF home-ready: median ${median(times).toFixed(0)} ms over ${RUNS} runs, cold cache (budget 1500 ms); runs ${times.map((t) => t.toFixed(0)).join(', ')}`);
  console.log(`PERF home-cls: worst ${Math.max(...shifts).toFixed(3)} over ${RUNS} runs (budget ${CLS_BUDGET}); runs ${shifts.map((s) => s.toFixed(3)).join(', ')}`);
  expect(median(times)).toBeLessThan(1500);
  expect(Math.max(...shifts)).toBeLessThan(CLS_BUDGET);
});

test('a review action round-trips under 150 ms', async ({ page }) => {
  await loginAs(page, 'spouse');
  await page.goto('/review');
  await listView(page);
  const durations: number[] = [];
  for (let i = 0; i < 10; i++) {
    const card = page.locator('[data-testid=review-card]').first();
    await card.waitFor();
    const id = await card.getAttribute('data-id');
    const pinned = page.locator(`[data-testid=review-card][data-id="${id}"]`);
    // Leave the household's matching rows for the Review spec's box test.
    const also = pinned.getByRole('checkbox', { name: /^Also the / });
    if (await also.count()) await also.uncheck();
    const countBefore = await page.evaluate(() => performance.getEntriesByName('review-action').length);
    await pinned.locator('.chips button:not(.chip--more)').first().click();
    // waitFor, not expect(...).toBeVisible(): Playwright's expect polls the page with a heavy in-page script that, on this
    // 100-card list, blocks the page's main thread for about 80 ms right as the reply lands, and that wait was counted in
    // the measure. The app's own work between the tap and the reply is about 1 ms.
    await page.locator(`[data-testid=slim-row][data-id="${id}"]`).waitFor();
    expect(await page.evaluate(() => performance.getEntriesByName('review-action').length)).toBe(countBefore + 1);
    durations.push(await page.evaluate(() => { const m = performance.getEntriesByName('review-action').pop() as PerformanceMeasure; return m.duration; }));
  }
  durations.sort((a, b) => a - b);
  const p95 = durations[Math.ceil(0.95 * (durations.length - 1))];
  console.log(`PERF review-action: p95 ${p95.toFixed(0)} ms over 10 taps (budget 150 ms)`);
  expect(p95).toBeLessThan(150);
});

test('a focus sort, from the tap to the next card taking actions, under 400 ms', async ({ page }) => {
  await loginAs(page, 'spouse');
  await page.goto('/review');
  const durations: number[] = [];
  for (let i = 0; i < 10; i++) {
    const card = page.locator('[data-testid=focus-card][data-role=current]');
    const id = await card.getAttribute('data-id');
    // Leave the household's matching rows for the Review spec's box test.
    const also = card.getByRole('checkbox', { name: /^Also the / });
    if (await also.count()) await also.uncheck();
    const n = await page.evaluate(() => performance.getEntriesByName('focus-action').length);
    await card.locator('.chips button:not(.chip--more)').first().click();
    await expect(page.locator('[data-testid=focus-card][data-role=current]')).not.toHaveAttribute('data-id', id!);
    expect(await page.evaluate(() => performance.getEntriesByName('focus-action').length)).toBe(n + 1);
    durations.push(await page.evaluate(() => (performance.getEntriesByName('focus-action').pop() as PerformanceMeasure).duration));
  }
  durations.sort((a, b) => a - b);
  const p95 = durations[Math.ceil(0.95 * (durations.length - 1))];
  console.log(`PERF focus-action: p95 ${p95.toFixed(0)} ms over 10 sorts (budget 400 ms)`);
  expect(p95).toBeLessThan(400);
});

// Nearest-rank p95: with 20 samples it is the 19th, so one outlier does not decide the budget.
const p95Of = (xs: number[]) => [...xs].sort((a, b) => a - b)[Math.ceil(0.95 * xs.length) - 1];
const LEVER_MOVES = 20;

// Plan subpages: the lever test runs on Try changes, which re-renders only the pinned bar and the lever rows. It was
// 500 ms on the whole page; 350 ms here. If the dev machine can't reach 350, set this to the measured p95 × 1.15, rounded up
// to 10 ms and never above 500, and say so in the PR (the spec's rule).
const LEVER_BUDGET_MS = 350;

test(`a lever move updates the ages in under ${LEVER_BUDGET_MS} ms`, async ({ page }) => {
  await loginAs(page, 'alex');
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 30, downloadThroughput: (25 * 1024 * 1024) / 8, uploadThroughput: (10 * 1024 * 1024) / 8 });
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
  await page.goto('/plan/try');
  await expect(page.getByTestId('age-comfortable')).toBeVisible();
  await page.getByTestId('lever-save_more').locator('.lever__head').click();
  const slider = page.getByTestId('slider-save_more');
  const previews = () => page.evaluate(() => performance.getEntriesByName('plan-preview').length);

  // Start at a run-unique, step-aligned value (as tests/perf/test_plan_budgets.py does), so the timed moves are never
  // answered from the server's result cache. 20 steps of 5000 up from at most 200000 stay within the scale (hi 300000).
  const now = Number(await slider.inputValue());
  let start = now;
  while (start === now) start = Math.floor(Math.random() * 41) * 5000;
  const before = await previews();
  await slider.fill(String(start));
  await page.waitForFunction((n) => performance.getEntriesByName('plan-preview').length > n, before);
  await slider.focus();
  await page.evaluate(() => performance.clearResourceTimings());

  const durations: number[] = [];
  const ttfbs: number[] = [];
  for (let i = 0; i < LEVER_MOVES; i++) {
    const n = await previews();
    await page.keyboard.press('ArrowRight'); // each press is a new value, so a cache miss
    await page.waitForFunction((k) => performance.getEntriesByName('plan-preview').length > k, n);
    const { duration, ttfb } = await page.evaluate(() => {
      const m = performance.getEntriesByName('plan-preview').pop() as PerformanceMeasure;
      const r = (performance.getEntriesByType('resource') as PerformanceResourceTiming[]).filter((e) => e.name.includes('/plan/preview')).pop()!;
      return { duration: m.duration, ttfb: r.responseStart - r.requestStart };
    });
    durations.push(duration);
    ttfbs.push(ttfb);
  }
  const p95 = p95Of(durations);
  const client = durations.map((d, i) => d - ttfbs[i]);
  console.log(`PERF plan-preview: p95 ${p95.toFixed(0)} ms over ${durations.length} moves from ${start}, request sent to ages shown (budget ${LEVER_BUDGET_MS} ms); `
    + `server TTFB median ${median(ttfbs).toFixed(0)} ms, p95 ${p95Of(ttfbs).toFixed(0)} ms; client (the rest) median ${median(client).toFixed(0)} ms, p95 ${p95Of(client).toFixed(0)} ms; `
    + `runs ${durations.map((d) => d.toFixed(0)).join(', ')}`);
  // A median TTFB under 50 ms (with the 30 ms emulated round trip) means the result cache answered, not the solver.
  expect(median(ttfbs)).toBeGreaterThanOrEqual(50);
  expect(p95).toBeLessThan(LEVER_BUDGET_MS);
});

test('the first status line shows under 300 ms after Send', async ({ page }) => {
  await loginAs(page, 'cass-phone', CHAT_PW);
  await chatOn(page, 'ours');
  await page.request.post('/api/b/ours/chat/seen', { data: {} });
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 30, downloadThroughput: (25 * 1024 * 1024) / 8, uploadThroughput: (10 * 1024 * 1024) / 8 });
  const times: number[] = [];
  try {
    for (let i = 0; i < RUNS; i++) {
      await page.goto('/b/ours/ask');
      await page.getByLabel('Your question').fill(`How much is in savings, run ${i + 1}?`);
      await expect(page.locator('.willsend__text').first()).not.toHaveText('…');
      await page.evaluate(() => { performance.clearMarks('ask-send'); performance.clearMarks('ask-first-status'); });
      await page.getByRole('button', { name: 'Send' }).click();
      await page.waitForFunction(() => performance.getEntriesByName('ask-first-status').length > 0);
      times.push(await page.evaluate(() => performance.measure('ask-status', 'ask-send', 'ask-first-status').duration));
      await expect(page.locator('.amsg__meta').last()).toBeVisible();
    }
  } finally {
    await chatOn(page, 'ours', false);
  }
  console.log(`PERF ask-first-status: median ${median(times).toFixed(0)} ms over ${RUNS} runs (budget 300 ms); runs ${times.map((t) => t.toFixed(0)).join(', ')}`);
  expect(median(times)).toBeLessThan(300);
});
