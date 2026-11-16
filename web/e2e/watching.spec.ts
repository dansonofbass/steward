import { expect, test, type Page } from '@playwright/test';
import { loginAs, restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

// Margaret's flags, seeded per project by seed_extra.py (seed_watching), so phone and desktop never share writes.
// The tests run in order: reading first, then the ones that mark flags.
const seeded = (project: string) => `margaret-ellis-seed-${project}`;
async function shot(page: Page, project: string, name: string) {
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: `e2e/screenshots-watching/${project}-${name}.png`, fullPage: true });
}
const NO_GENDER = /\b(her|hers|she)\b/i;

test.describe.serial('watching', () => {
  test.beforeEach(async ({ page }) => { await page.addInitScript(() => localStorage.setItem('steward-theme', 'light')); });

  test("Home puts the flags first and Home's tab shows the count in red", async ({ page }, info) => {
    const slug = seeded(info.project.name);
    await loginAs(page, 'alex');
    await page.goto(`/b/${slug}`);
    const block = page.getByRole('region', { name: 'Look into' });
    await expect(block.getByText('3 urgent')).toBeVisible();
    await expect(block.getByTestId('flag-row')).toHaveCount(5);
    await expect(block.getByText(/1 more: Duplicate/)).toBeVisible();
    await expect(page.getByRole('link', { name: 'Home, 6 to look into' })).toBeVisible();
    await expect(page.locator('.nav__count--urgent')).toHaveText('6');
    expect(await page.locator('main').innerText()).not.toMatch(NO_GENDER);
    await shot(page, info.project.name, 'home');
  });

  test('Look into groups urgent first, and Done keeps what was marked', async ({ page }, info) => {
    const slug = seeded(info.project.name);
    await loginAs(page, 'alex');
    await page.goto(`/b/${slug}/look-into`);
    await expect(page.getByText('Urgent · 3')).toBeVisible();
    await expect(page.getByText('Other · 3')).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: /Home/ })).toHaveAttribute('aria-current', 'page');
    await shot(page, info.project.name, 'list');
    await page.getByRole('group', { name: 'Show' }).getByRole('button', { name: /Done/ }).click();
    await expect(page.getByText(/\$640.00 to Brea Family Dental/)).toBeVisible();
    await expect(page.getByTestId('flag-row')).toHaveCount(3);
    expect(await page.locator('main').innerText()).not.toMatch(NO_GENDER);
    await shot(page, info.project.name, 'done');
  });

  test('a viewer reads the flags and cannot mark them', async ({ page }, info) => {
    const slug = seeded(info.project.name);
    await loginAs(page, `vee-${info.project.name}`, 'pw-viewer-demo-2026');
    await page.goto(`/b/${slug}`);
    await expect(page.getByRole('link', { name: 'Home, 6 to look into' })).toBeVisible();
    await page.goto(`/b/${slug}/look-into`);
    await expect(page.getByText('You can see this book but not change it.')).toBeVisible();
    await shot(page, info.project.name, 'viewer-list');
    await page.getByTestId('flag-row').filter({ hasText: 'Ralphs' }).click();
    await expect(page.getByText(/is checking:/)).toBeVisible();
    await expect(page.getByRole('region', { name: 'What did you find?' })).toHaveCount(0);
    await expect(page.getByText('Only managers can mark flags.', { exact: false })).toBeVisible();
    await shot(page, info.project.name, 'viewer-flag');
  });

  test("the document page names who prepared it (part 2's parked item)", async ({ page }, info) => {
    const slug = seeded(info.project.name);
    await loginAs(page, 'alex');
    await page.goto(`/b/${slug}/inventory`);
    await page.getByTestId('item-row').filter({ hasText: 'Durable power of attorney' }).click();
    await expect(page.getByRole('link', { name: 'Linda Park, Park & Reyes Law' })).toBeVisible();
  });

  test('the missed premium page names the policy and shows the account', async ({ page }, info) => {
    const slug = seeded(info.project.name);
    await loginAs(page, 'alex');
    await page.goto(`/b/${slug}/look-into`);
    await page.getByTestId('flag-row').filter({ hasText: 'Evergreen Mutual' }).click();
    await expect(page.getByText('Missed premium').first()).toBeVisible();
    await expect(page.getByText(/Evergreen Mutual long-term care premium/).first()).toBeVisible();
    expect(await page.locator('main').innerText()).not.toMatch(NO_GENDER);
    await shot(page, info.project.name, 'flag-premium');
  });

  test('the gift card: Still checking, then Handled with the note it needs', async ({ page }, info) => {
    const slug = seeded(info.project.name);
    await loginAs(page, 'alex');
    await page.goto(`/b/${slug}/look-into`);
    await page.getByTestId('flag-row').filter({ hasText: 'gift card' }).click();
    await expect(page.getByRole('heading', { name: '$500.00 gift card at CVS Pharmacy' })).toBeVisible();
    await expect(page.getByText('None were gift cards.', { exact: false })).toBeVisible();
    await expect(page.getByText('Also matched:')).toBeVisible();
    expect(await page.locator('main').innerText()).not.toMatch(NO_GENDER);
    await shot(page, info.project.name, 'flag');
    await page.getByRole('region', { name: 'What did you find?' }).getByRole('button', { name: 'Still checking' }).click();
    const checking = page.getByRole('dialog', { name: 'Mark Still checking' });
    await checking.getByLabel('Note (optional)').fill('Calling Margaret this morning to ask about it.');
    await checking.getByRole('button', { name: 'Mark Still checking' }).click();
    await expect(page.getByText('Alex is checking:')).toBeVisible();
    await shot(page, info.project.name, 'flag-checking');
    await page.getByRole('region', { name: 'What did you find?' }).getByRole('button', { name: 'Handled' }).click();
    const handled = page.getByRole('dialog', { name: 'Mark Handled' });
    await handled.getByRole('button', { name: 'Mark Handled' }).click();
    await expect(handled.getByText('Add a note saying what was done.')).toBeVisible();
    await handled.getByLabel('What was done?').fill('Called CVS and the card company and reported it to the bank.');
    await shot(page, info.project.name, 'flag-handled-sheet');
    await handled.getByRole('button', { name: 'Mark Handled' }).click();
    await expect(page.getByRole('button', { name: 'Reopen' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Home, 5 to look into' })).toBeVisible();
  });

  test('marking a flag Expected adds a known payee, which can be removed', async ({ page }, info) => {
    const slug = seeded(info.project.name);
    await loginAs(page, 'alex');
    await page.goto(`/b/${slug}/look-into`);
    await page.getByTestId('flag-row').filter({ hasText: 'StreamBox' }).click();
    await page.getByRole('region', { name: 'What did you find?' }).getByRole('button', { name: 'Expected' }).click();
    const sheet = page.getByRole('dialog', { name: 'Mark Expected' });
    await expect(sheet.getByRole('radio', { name: /Not for about this amount/ })).toBeChecked();
    await shot(page, info.project.name, 'expected-sheet');
    await sheet.getByLabel('Note (optional)').fill('Margaret watches it every evening.');
    await sheet.getByRole('button', { name: 'Mark Expected' }).click();
    await expect(page.getByText('Marked Expected. StreamBox, $11.99 to $19.98, added to Known payees.')).toBeVisible();
    await page.goto(`/b/${slug}/settings/watching/known`);
    await expect(page.getByText('StreamBox', { exact: true })).toBeVisible();
    await shot(page, info.project.name, 'known');
    await page.locator('.kp').filter({ hasText: 'StreamBox' }).getByRole('button', { name: 'Remove' }).click();
    const remove = page.getByRole('dialog', { name: 'Remove StreamBox?' });
    await remove.getByLabel('Why (optional)').fill('Cancelled the subscription.');
    await remove.getByRole('button', { name: 'Remove' }).click();
    await expect(page.locator('.kp').filter({ hasText: 'StreamBox' })).toHaveCount(0);
  });

  test('Settings → Watching: the large amount, the floors and the last-manager rule', async ({ page }, info) => {
    const slug = seeded(info.project.name);
    await loginAs(page, 'alex');
    await page.goto(`/b/${slug}/settings/watching`);
    await expect(page.getByText('under its floor')).toBeVisible();
    await expect(page.getByLabel('Floor for Way2Save savings')).toHaveValue('25,000');
    const large = page.getByLabel('Flag money out of');
    await large.fill('750.00');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0);
    await page.getByRole('switch', { name: 'Urgent emails for Alex' }).click();
    await expect(page.getByText('At least one manager has to get urgent emails.', { exact: false })).toBeVisible();
    await shot(page, info.project.name, 'settings');
    await page.goto(`/b/${slug}/settings/changes`);
    await page.getByLabel('Kind of change').selectOption('watching');
    await expect(page.getByText('changed the large amount')).toBeVisible();
    await expect(page.getByText(/marked .* Expected/).first()).toBeVisible();
    expect(await page.locator('main').innerText()).not.toMatch(NO_GENDER);
    await shot(page, info.project.name, 'changes');
  });
});
