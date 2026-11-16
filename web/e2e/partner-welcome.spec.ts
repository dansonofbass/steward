import { expect, test } from '@playwright/test';
import { loginAs, logout, restoreVault, youMenu } from './fixtures';

// A partner's welcome (guided setup spec 7): three screens after accepting an invite, once. seed_extra.py gives each
// project a pending manager invite for wren-<project> whose token is built here.
test.describe.configure({ mode: 'serial' });
test.beforeAll(async () => { await restoreVault(); });

const WREN_PW = 'pw-partner-demo-2026';
const names = (project: string) => ({
  wren: `wren-${project}`, slug: `dad-seed-${project}`, book: `Dad (Seed ${project})`,
  token: ['e2e', 'partner', 'token', project].join('-'),
});

test('accept an invite, three screens, Home', async ({ page }, info) => {
  const { wren, slug, book, token } = names(info.project.name);
  await loginAs(page, wren, WREN_PW);
  await page.goto(`/invite?token=${token}`);
  await expect(page).toHaveURL(new RegExp(`/b/${slug}/welcome$`));
  await expect(page.getByRole('heading', { name: `Welcome to ${book}`, level: 1 })).toBeVisible();
  await expect(page.locator('.welcome__acorn')).toHaveCount(0);
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your switches', level: 1 })).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your name on your work', level: 1 })).toBeVisible();
  await expect(page.getByText(/^Notes and sorts show who made them\./)).toBeVisible();
  await page.getByRole('button', { name: 'Go to Home' }).click();
  await expect(page).toHaveURL(new RegExp(`/b/${slug}$`));
});

test('never again on the next sign-in, and again from Help', async ({ page }, info) => {
  const { wren, slug } = names(info.project.name);
  await loginAs(page, wren, WREN_PW);
  await logout(page);
  await loginAs(page, wren, WREN_PW);
  await page.goto('/');
  await expect(page).toHaveURL(new RegExp(`/b/${slug}$`));
  await youMenu(page);
  await page.getByRole('link', { name: 'Help' }).click();
  await page.getByRole('link', { name: 'See the welcome again' }).click();
  await expect(page).toHaveURL(new RegExp(`/b/${slug}/welcome\\?again=1$`));
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your name on your work', level: 1 })).toBeVisible();
  await page.getByRole('button', { name: 'Skip', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/b/${slug}$`));
  const me = await (await page.request.get('/api/auth/me')).json();
  expect(me.books.find((b: { slug: string }) => b.slug === slug).welcome).toBeNull();
});
