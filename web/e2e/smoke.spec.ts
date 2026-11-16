import { expect, test } from '@playwright/test';
import { loginAs, restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

test('unauthenticated visit goes to sign-in and comes back after sign-in', async ({ page }) => {
  await page.goto('/transactions');
  await expect(page).toHaveURL(/\/login\?next=%2Ftransactions/);
  await expect(page.getByRole('heading', { name: 'Steward' })).toBeVisible();
  await loginAs(page, 'alex');
  await page.goto('/transactions');
  await expect(page.getByRole('heading', { name: 'All transactions' })).toBeVisible();
});

test('api is served from the same origin', async ({ page }) => {
  const r = await page.request.get('/api/health');
  expect(r.ok()).toBeTruthy();
  const h = await page.request.get('/assets/does-not-exist.js');
  expect(h.status()).toBe(404); // a missing asset fails cleanly instead of returning HTML
});

test('the favicon set and the manifest are served from the built app, signed out', async ({ page }) => {
  const svg = await page.request.get('/favicon.svg');
  expect(svg.status()).toBe(200);
  expect(svg.headers()['content-type']).toMatch(/^image\/svg\+xml/);
  expect(await svg.text()).toContain('prefers-color-scheme:dark');
  const manifest = await page.request.get('/manifest.webmanifest');
  expect(manifest.status()).toBe(200);
  expect(manifest.headers()['content-type']).toMatch(/^application\/manifest\+json/);
  const m = await manifest.json();
  expect(m.name).toBe('Steward');
  for (const icon of [...m.icons.map((i: { src: string }) => i.src), '/apple-touch-icon.png', '/favicon-32.png', '/favicon-16.png']) {
    const r = await page.request.get(icon);
    expect(r.status(), icon).toBe(200);
    expect(r.headers()['content-type'], icon).toBe('image/png');
  }
});
