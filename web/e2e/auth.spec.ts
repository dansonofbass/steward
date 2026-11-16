import { expect, test, type Page } from '@playwright/test';
import { DEMO, loginAs, logout, youMenu, restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

async function addVirtualAuthenticator(page: Page) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  const { authenticatorId } = await cdp.send('WebAuthn.addVirtualAuthenticator', {
    options: { protocol: 'ctap2', transport: 'internal', hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true },
  });
  return { cdp, authenticatorId };
}

test('password sign-in and the lockout message', async ({ page }, testInfo) => {
  const user = `locky-${testInfo.project.name}`;
  await page.goto('/login');
  for (let i = 0; i < 5; i++) {
    await page.getByLabel('Username').fill(user);
    await page.getByLabel('Password').fill('wrong-password-1');
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(page.getByText("That username or password isn't right.")).toBeVisible();
  }
  await page.getByLabel('Password').fill('wrong-password-1');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByText('Too many tries. Try again in 15 minutes.')).toBeVisible();
});

test('signing in returns to the page that was asked for', async ({ page }) => {
  await page.goto('/review');
  await expect(page).toHaveURL(/\/login\?next=%2Freview/);
  await page.getByLabel('Username').fill('alex');
  await page.getByLabel('Password').fill('pw-demo-alex-2026');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/review$/);
});

test('a book address asked for signed out comes back after sign-in, once', async ({ page }) => {
  await page.goto('/b/ours/review');
  await expect(page).toHaveURL(/\/login\?next=%2Fb%2Fours%2Freview$/);
  await page.getByLabel('Username').fill('alex');
  await page.getByLabel('Password').fill('pw-demo-alex-2026');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/b\/ours\/review$/);
});

test('revoked session returns to the same screen after sign-in', async ({ page }) => {
  await loginAs(page, 'spouse');
  await page.goto('/transactions');
  await expect(page.getByRole('heading', { name: 'All transactions' })).toBeVisible();
  await page.waitForLoadState('networkidle');                // the screen's own loads (rows, Review badge) finish first
  const me = await (await page.request.get('/api/auth/me')).json();
  await page.request.delete(`/api/auth/sessions/${me.session.id}`);
  await page.getByLabel('Search').fill('coffee');            // an in-app data call sees 401; the client's handler redirects
  await expect(page).toHaveURL(/\/login\?next=%2Fb%2Fours%2Ftransactions/);
  await page.getByLabel('Username').fill('spouse');
  await page.getByLabel('Password').fill('pw-demo-spouse-2026');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/b\/ours\/transactions\?q=coffee$/);           // back where they were, search kept
});

test('register a passkey, sign out, sign in with it', async ({ page }) => {
  await addVirtualAuthenticator(page);
  await loginAs(page, 'alex');
  await page.goto('/settings/people');                     // the old address lands on Sign-in and devices
  await expect(page.getByRole('heading', { name: 'Sign-in and devices', level: 1 })).toBeVisible();
  await page.getByRole('button', { name: 'Add this device' }).click();
  await page.getByLabel('Name this device').fill("Alex's test phone");
  await page.getByLabel('Your password').fill(DEMO.alex);
  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByLabel('Name this device')).toHaveCount(0); // the sheet closes when registration is done (the phone run already left a same-named row)
  await expect(page.getByText("Alex's test phone").first()).toBeVisible(); // the phone run left one too
  await logout(page);
  await page.goto('/login');
  await page.getByRole('button', { name: 'Sign in with a passkey' }).click();
  await expect(page).toHaveURL(/\/$/);
  expect((await page.request.get('/api/auth/me')).status()).toBe(200);
});

test('deleted passkey is refused in plain words', async ({ page }) => {
  await addVirtualAuthenticator(page);
  await loginAs(page, 'spouse');
  await page.goto('/settings/people');
  await expect(page.getByRole('heading', { name: 'Sign-in and devices', level: 1 })).toBeVisible();
  await page.getByRole('button', { name: 'Add this device' }).click();
  await page.getByLabel('Name this device').fill('Old phone');
  await page.getByLabel('Your password').fill(DEMO.spouse);
  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByText('Old phone')).toBeVisible();
  await page.getByRole('button', { name: 'Remove Old phone' }).click();
  await page.getByRole('dialog', { name: 'Remove the passkey Old phone?' }).getByRole('button', { name: 'Remove' }).click();
  await expect(page.getByText('Removed the passkey Old phone.')).toBeVisible(); // the removal line says what went
  await expect(page.getByText('Old phone', { exact: true })).toHaveCount(0); // and the row is gone
  await expect(page.getByRole('button', { name: 'Remove Old phone' })).toHaveCount(0);
  await logout(page);
  await page.goto('/login');
  await page.getByRole('button', { name: 'Sign in with a passkey' }).click();
  await expect(page.getByText("That passkey isn't registered any more. Sign in with your password and add it again.")).toBeVisible();
  await expect(page.getByLabel('Password')).toBeEnabled();
});

test('Sign out in the You menu asks first, then signs this device out', async ({ page }) => {
  await loginAs(page, 'spouse');
  await page.goto('/');
  await youMenu(page);
  await page.getByRole('button', { name: 'Sign out' }).click();
  const confirm = page.getByRole('dialog', { name: 'Sign out of this device?' });
  await confirm.getByRole('button', { name: 'Cancel' }).click();
  await expect(confirm).toBeHidden();
  expect((await page.request.get('/api/auth/me')).status()).toBe(200);
  await youMenu(page);
  await page.getByRole('button', { name: 'Sign out' }).click();
  await confirm.getByRole('button', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect((await page.request.get('/api/auth/me')).status()).toBe(401);
});

test('forgot password shows the neutral message', async ({ page }) => {
  await page.goto('/login');
  await page.getByRole('link', { name: 'Forgot your password?' }).click();
  await page.getByLabel('Username or email').fill('alex');
  await page.getByRole('button', { name: 'Send me a link' }).click();
  await expect(page.getByText('If that account exists, we sent a link. It works for 15 minutes.')).toBeVisible();
});

test('reset with a bad token says so', async ({ page }) => {
  await page.goto('/reset?token=not-a-real-token');
  await page.getByLabel('New password').fill('a-brand-new-password-1');
  await page.getByRole('button', { name: 'Change password' }).click();
  await expect(page.getByText('That link has expired or was already used.')).toBeVisible();
});
