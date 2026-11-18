import { expect, test } from '@playwright/test';
import { loginAs, restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

type Violation = { directive: string; blocked: string };
type Seen = { violations: Violation[]; moments: number };
const seen = () => (window as unknown as { __seen: Seen }).__seen;

// Hardening plan, Engineering choice 6: the page runs under the CSP, its one inline script allowed by the hash the
// server read from the built index.html, and Chromium blocks nothing on sign-in, a list screen or Settings. Issue #14
// adds Trusted Types: a sort's celebration puts its SVG in through the one named policy, and nothing is blocked.
test('pages run under the CSP and nothing is blocked', async ({ page }) => {
  const blocked: string[] = [];
  page.on('console', (m) => { if (/Content Security Policy|Trusted ?Type/i.test(m.text())) blocked.push(m.text()); });
  page.on('pageerror', (e) => { if (/Trusted ?Type|TrustedHTML/i.test(e.message)) blocked.push(e.message); });
  await page.addInitScript(() => {
    const s: Seen = { violations: [], moments: 0 };
    (window as unknown as { __seen: Seen }).__seen = s;
    document.addEventListener('securitypolicyviolation', (e) => s.violations.push({ directive: e.effectiveDirective, blocked: e.blockedURI }));
    new MutationObserver((records) => {
      for (const r of records) for (const n of r.addedNodes) if (n instanceof Element && n.matches('.cel-moment') && n.querySelector('svg')) s.moments++;
    }).observe(document, { childList: true, subtree: true });
  });
  const first = await page.goto('/login');
  const headers = first?.headers() ?? {};
  const csp = headers['content-security-policy'] ?? '';
  expect(csp).toContain("default-src 'self'");
  expect(csp).toMatch(/script-src 'self' 'sha256-[A-Za-z0-9+/]+=*'/);
  for (const d of ["require-trusted-types-for 'script'", 'trusted-types celebrate', 'report-uri /api/csp-report', 'report-to csp']) {
    expect(csp).toContain(d);
  }
  expect(headers['x-frame-options']).toBe('DENY');
  expect(headers['permissions-policy']).toContain('camera=()');
  expect(headers['permissions-policy']).not.toContain('publickey-credentials');
  expect(headers['reporting-endpoints']).toBe('csp="/api/csp-report"');
  await expect(page.getByRole('heading', { name: 'Steward' })).toBeVisible();
  await loginAs(page, 'alex');
  await page.goto('/transactions');
  await expect(page.getByRole('heading', { name: 'All transactions' })).toBeVisible();
  await page.goto('/settings/people');
  await expect(page.getByRole('heading', { name: 'Sign-in and devices', level: 1 })).toBeVisible();
  await page.goto('/review');
  const card = page.locator('[data-testid=focus-card][data-role=current]');
  const also = card.getByRole('checkbox', { name: /^Also the / });
  if (await also.count()) await also.uncheck();
  await card.locator('.chips button:not(.chip--more)').first().click();
  await expect.poll(async () => (await page.evaluate(seen)).moments).toBe(1);   // its SVG went in under Trusted Types
  expect((await page.evaluate(seen)).violations).toEqual([]);
  expect(blocked).toEqual([]);
});
