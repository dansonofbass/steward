import { expect, test } from '@playwright/test';
import { loginAs, restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

// Hardening plan, Engineering choice 6: the page runs under the CSP, its one inline script allowed by the hash the
// server read from the built index.html, and Chromium blocks nothing on sign-in, a list screen or Settings.
test('pages run under the CSP and nothing is blocked', async ({ page }) => {
  const blocked: string[] = [];
  page.on('console', (m) => { if (/Content Security Policy/i.test(m.text())) blocked.push(m.text()); });
  const first = await page.goto('/login');
  const csp = first?.headers()['content-security-policy'] ?? '';
  expect(csp).toContain("default-src 'self'");
  expect(csp).toMatch(/script-src 'self' 'sha256-[A-Za-z0-9+/]+=*'/);
  await expect(page.getByRole('heading', { name: 'Steward' })).toBeVisible();
  await loginAs(page, 'alex');
  await page.goto('/transactions');
  await expect(page.getByRole('heading', { name: 'All transactions' })).toBeVisible();
  await page.goto('/settings/people');
  await expect(page.getByRole('heading', { name: 'Sign-in and devices', level: 1 })).toBeVisible();
  expect(blocked).toEqual([]);
});
