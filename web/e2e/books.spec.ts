import { expect, test, type Page } from '@playwright/test';
import { loginAs, logout, tab, youMenu, restoreVault, animationsSettled } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

// One parent book per Playwright project, so the phone and desktop runs never meet. Each project also has a seeded
// parent book ("Dad (Seed <project>)") with a pending viewer invite for vee-<project>; the invite email can't be read
// from a test, so seed_extra.py gives the invite a known token.
const names = (project: string) => ({
  name: `Mom (Test ${project})`, slug: `mom-test-${project}`, viewer: `vee-${project}`,
  seedSlug: `dad-seed-${project}`, token: `e2e-invite-token-${project}`,
});

// Screenshots for the design pass (not committed): the phone project is 390 px wide, the desktop one 1280 px.
async function shot(page: Page, project: string, name: string) {
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: `e2e/screenshots-books/${project}-${name}.png` });
}

test.describe.serial('books', () => {
  test('a manager adds a parent book and an item in it', async ({ page }, info) => {
    const { name, slug } = names(info.project.name);
    await loginAs(page, 'alex');
    await page.goto('/b/ours');
    await youMenu(page);
    await page.getByRole('link', { name: 'Settings for Ours' }).click();
    await page.getByRole('link', { name: 'Books', exact: true }).click();
    await expect(page).toHaveURL(/\/b\/ours\/settings\/books$/);
    await shot(page, info.project.name, 'settings-books');
    await page.getByRole('button', { name: 'Add a book' }).click();
    const sheet = page.getByRole('dialog', { name: 'Add a book' });
    await sheet.getByLabel('Name', { exact: true }).fill(name);
    await sheet.getByLabel('Owner names 1', { exact: true }).fill('Margaret');
    await sheet.getByRole('button', { name: 'Add book' }).click();
    await expect(page).toHaveURL(new RegExp(`/b/${slug}/settings/members$`));
    await expect(page.getByText(`${name} added. Add the people who help with it.`)).toBeVisible();
    await expect(tab(page, 'Plan')).toHaveCount(0);
    await shot(page, info.project.name, 'settings-members');

    await page.goto(`/b/${slug}/inventory/new?kind=account`);
    await page.getByLabel('Type', { exact: true }).selectOption('checking');
    await page.getByLabel('Name', { exact: true }).fill('Mom checking');
    await page.getByRole('radio', { name: 'Margaret' }).check({ force: true });
    await page.getByLabel('Balance', { exact: true }).fill('1200');
    await page.getByRole('button', { name: 'Add item' }).click();
    await expect(page.getByRole('heading', { name: 'Mom checking' })).toBeVisible();
    await page.goto(`/b/${slug}/inventory`);
    await expect(page.getByText('Mom checking')).toBeVisible();
    await page.goto(`/b/${slug}`);
    await expect(page.getByText('Net worth, known items')).toBeVisible();
    await shot(page, info.project.name, 'parent-home');
  });

  test('switching books keeps their money apart', async ({ page }, info) => {
    const { name, slug } = names(info.project.name);
    await loginAs(page, 'alex');
    await page.goto(`/b/${slug}/inventory`);
    await expect(page.getByText('Mom checking')).toBeVisible();
    await page.getByRole('button', { name: `Switch book: ${name}` }).click();
    await expect(page.getByRole('link', { name: /^Ours/ })).toBeVisible();
    await animationsSettled(page);   // the sheet has finished sliding up
    await shot(page, info.project.name, 'switcher-open');
    await page.getByRole('link', { name: /^Ours/ }).click();
    await expect(page).toHaveURL(/\/b\/ours$/);
    await expect(page.getByTestId('account-row').first()).toBeVisible();   // Ours's own accounts have loaded
    await expect(page.getByText('Mom checking')).toHaveCount(0);
    await page.getByRole('button', { name: 'Switch book: Ours' }).click();
    await page.getByRole('link', { name: new RegExp(`^${name.replace(/[()]/g, '\\$&')}`) }).click();
    await expect(page).toHaveURL(new RegExp(`/b/${slug}$`));
    await page.goto(`/b/${slug}/inventory`);
    await expect(page.getByText('Mom checking')).toBeVisible();
  });

  test('a book in Settings, Books opens its details without switching; Open switches', async ({ page }, info) => {
    const { name, slug } = names(info.project.name);
    await loginAs(page, 'alex');
    await page.goto('/b/ours/settings/books');
    await page.getByRole('link', { name: new RegExp(`^${name.replace(/[()]/g, '\\$&')}`) }).click();
    await expect(page).toHaveURL(new RegExp(`/b/ours/settings/books/${slug}$`));   // still in Ours
    await expect(page.getByRole('heading', { name, level: 2 })).toBeVisible();
    await expect(page.getByText('Managers')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Switch book: Ours' })).toBeVisible();
    await page.getByRole('link', { name: `Open ${name}` }).click();
    await expect(page).toHaveURL(new RegExp(`/b/${slug}$`));
    await expect(page.getByRole('button', { name: `Switch book: ${name}` })).toBeVisible();
  });

  test('inviting someone without a Steward account sends an invite and adds nobody yet', async ({ page }, info) => {
    const { slug } = names(info.project.name);
    const email = `guest-${info.project.name}@example.com`;
    await loginAs(page, 'alex');
    await page.goto(`/b/${slug}/settings/members`);
    await page.getByRole('button', { name: 'Invite someone' }).click();
    const sheet = page.getByRole('dialog', { name: 'Invite someone' });
    await sheet.getByLabel('Email', { exact: true }).fill(email);
    await sheet.getByLabel('Name', { exact: true }).fill('Guest');
    await sheet.getByRole('button', { name: 'Invite' }).click();
    await expect(page.getByText(`Invite sent to ${email}.`)).toBeVisible();
    await expect(page.getByText('Invited').first()).toBeVisible();
  });

  test('a viewer accepts an invite, sees the book and cannot change it', async ({ page }, info) => {
    const { seedSlug, viewer, token } = names(info.project.name);
    // Signed out, the invite link sends the person to sign in and comes back to it.
    await page.goto(`/invite?token=${token}`);
    await expect(page).toHaveURL(/\/login/);
    await loginAs(page, viewer, 'pw-viewer-demo-2026');
    await page.goto(`/invite?token=${token}`);
    await expect(page).toHaveURL(new RegExp(`/b/${seedSlug}/welcome$`));
    await expect(page.getByRole('heading', { name: /^Welcome to Dad \(Seed /, level: 1 })).toBeVisible();
    await page.getByRole('button', { name: 'Skip', exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/b/${seedSlug}$`));
    await expect(page.getByText('Net worth, known items')).toBeVisible();
    await page.goto(`/b/${seedSlug}/inventory`);
    await expect(page.getByText('Dad checking')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Add an item' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /Switch book/ })).toHaveCount(1);   // Margaret's book is seeded for this viewer too, so the switcher shows

    await page.goto('/');
    await expect(page).toHaveURL(new RegExp(`/b/${seedSlug}$`));
    await page.goto(`/b/${seedSlug}/settings`);
    // A viewer's Settings is what is theirs (feedback 2026-10-25, section 0): no Book members, but Books (they are in
    // two books), Watching (where they stop their own emails) and the change record. Only a manager adds a book.
    await expect(page.getByRole('link', { name: 'Books', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Book members' })).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'Watching' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Change record' })).toBeVisible();
    await page.getByRole('link', { name: 'Books', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Books', level: 2 })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Add a book' })).toHaveCount(0);

    await page.goto(`/b/${seedSlug}/review`);
    await expect(page.getByText('You can see this book but not change it.')).toBeVisible();
    const card = page.getByTestId('review-card').first();
    await expect(card).toBeVisible();
    const buttons = card.getByRole('button');
    expect(await buttons.count()).toBeGreaterThan(2);
    for (const b of await buttons.all()) await expect(b).toBeDisabled();

    await page.goto(`/b/${seedSlug}/transactions?dates=all`);
    await page.locator('[data-testid=txn-row]').first().click();
    const detail = page.getByTestId('txn-detail');
    await expect(detail.getByText('You can see this book but not change it.')).toBeVisible();
    await expect(detail.getByLabel('Category')).toBeDisabled();
    await expect(detail.getByRole('button', { name: 'Save' })).toBeDisabled();

    const r = await page.request.post(`/api/b/${seedSlug}/accounts`, { data: { name: 'x', type: 'checking', owner: 'joint', balance_cents: 0 } });
    expect(r.status()).toBe(403);
    expect((await r.json()).error).toBe('You can see this book but not change it.');
    const ours = await page.request.get('/api/b/ours/accounts');
    expect(ours.status()).toBe(404);
    await logout(page);
  });
});
