import { expect, test } from '@playwright/test';
import { loginAs, restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

test.beforeEach(async ({ page }) => { await loginAs(page, 'alex'); });

test('Taxes reads on a phone and a desktop with no sideways scroll', async ({ page }, info) => {
  const size = info.project.name === 'phone' ? { width: 360, height: 800 } : { width: 1440, height: 900 };
  await page.setViewportSize(size);
  await page.goto('/b/ours/taxes');
  await expect(page.getByRole('heading', { name: 'Taxes', level: 1 })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Quarterly taxes' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Solo 401(k) or SEP' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Roth or traditional' })).toBeVisible();
  await expect(page.getByText('Steward never pays or files anything.').first()).toBeVisible();
  const sideways = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(sideways).toBe(false);
  for (const box of await page.locator('.taxes button, .taxes .tax-check, .taxes a').all()) {
    const b = await box.boundingBox();
    if (b) expect(b.height).toBeGreaterThanOrEqual(44);
  }
  await page.screenshot({ path: `e2e/screenshots-taxes/taxes-${size.width}x${size.height}.png`, fullPage: true });
});

test('Taxes is a page of the Plan tab', async ({ page }) => {
  await page.goto('/plan');
  await page.getByRole('navigation', { name: 'Plan pages' }).getByRole('link', { name: 'Taxes', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Taxes', level: 1 })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Plan pages' }).getByRole('link')).toHaveText(['Overview', 'Try changes', 'Next dollar', 'How it works', 'Taxes']);
  await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Plan', exact: true })).toHaveAttribute('aria-current', 'page');
});
