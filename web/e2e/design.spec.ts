import { expect, test } from '@playwright/test';
import { restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

test.describe('theme', () => {
  test('dark first paint', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('steward-theme', 'dark'));
    await page.goto('/design');
    expect(await page.evaluate(() => document.documentElement.dataset.phase)).toBe('night');
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    expect(bg).toBe('rgb(14, 23, 41)'); // night --bg #0E1729
  });
  test('a stored light choice beats the clock', async ({ page }) => {
    await page.clock.setFixedTime(new Date('2026-10-13T03:00:00'));
    await page.addInitScript(() => localStorage.setItem('steward-theme', 'light'));
    await page.goto('/design');
    expect(await page.evaluate(() => document.documentElement.dataset.phase)).toBe('day');
    expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe('rgb(250, 248, 243)'); // day --bg #FAF8F3
  });
  test('with no stored choice the phase follows the clock', async ({ page }) => {
    await page.clock.setFixedTime(new Date('2026-10-13T03:00:00'));
    await page.goto('/design');
    expect(await page.evaluate(() => document.documentElement.dataset.phase)).toBe('night');
    await page.clock.setFixedTime(new Date('2026-10-13T12:00:00'));
    await page.reload();
    expect(await page.evaluate(() => document.documentElement.dataset.phase)).toBe('day');
  });
});

test('design page shows every primitive with labels and tabular money', async ({ page }) => {
  await page.goto('/design');
  await expect(page.getByRole('heading', { name: 'Design' })).toBeVisible();
  const money = page.locator('.money').first();
  expect(await money.evaluate((el) => getComputedStyle(el).fontVariantNumeric)).toContain('tabular-nums');
  for (const name of ['Home', 'Spending', 'Accounts', 'Ask', 'Plan', 'Review']) {
    await expect(page.getByRole('navigation', { name: 'Main' }).first().getByText(name)).toBeVisible();
  }
  const small = await page.locator('svg.lucide').evaluateAll((els) => els.filter((e) => e.getBoundingClientRect().width < 20).length);
  expect(small).toBe(0);
});
