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
type Authenticator = Awaited<ReturnType<typeof addVirtualAuthenticator>>;

/** The passkeys this device holds for Steward. */
async function held({ cdp, authenticatorId }: Authenticator) {
  return (await cdp.send('WebAuthn.getCredentials', { authenticatorId })).credentials;
}

/** As a browser without passkey autofill: Login offers passkeys through its button only. The virtual authenticator
 *  answers a waiting autofill request at once, so a test of the button turns autofill off first. */
async function withoutAutofill(page: Page) {
  await page.addInitScript(() => {
    Object.defineProperty(PublicKeyCredential, 'isConditionalMediationAvailable', { value: async () => false });
  });
}

/** Signs in as `username`, adds this device's passkey under `label` in Sign-in and devices, and signs out. */
async function addPasskey(page: Page, username: 'alex' | 'spouse', label: string) {
  await loginAs(page, username);
  await page.goto('/settings/people');                     // the old address lands on Sign-in and devices
  await expect(page.getByRole('heading', { name: 'Sign-in and devices', level: 1 })).toBeVisible();
  await page.getByRole('button', { name: 'Add this device' }).click();
  await page.getByLabel('Name this device').fill(label);
  await page.getByLabel('Your password').fill(DEMO[username]);
  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByLabel('Name this device')).toHaveCount(0); // the sheet closes when registration is done
}

// Issue #7: five wrong tries pause password sign-in for that account on this device, and the pause answers exactly as
// a wrong password does. Both browsers share an address, so the pause holds every device that hasn't signed in to the
// account; the member's own device, which signed in before, still signs in.
test('five wrong passwords pause sign-in here but not on a device that signed in before', async ({ page }, testInfo) => {
  const user = `locky-${testInfo.project.name}`;
  const signIn = async (password: string) => {
    await page.getByLabel('Password').fill(password);
    const answer = page.waitForResponse((r) => r.url().endsWith('/api/auth/login'));
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    expect((await answer).status()).toBe(401);
    await expect(page.getByText("That username or password isn't right.")).toBeVisible();
  };
  await page.goto('/login');
  const other = await page.context().browser()!.newContext({ baseURL: new URL(page.url()).origin });
  try {
    const there = await other.newPage();
    const signInThere = async () => {
      await there.goto('/login');
      await there.getByLabel('Username').fill(user);
      await there.getByLabel('Password').fill('pw-locky-demo-2026');
      await there.getByRole('button', { name: 'Sign in', exact: true }).click();
      await expect(there).not.toHaveURL(/\/login/);
    };
    await signInThere();
    await logout(there);
    await page.getByLabel('Username').fill(user);
    for (let i = 0; i < 5; i++) await signIn('wrong-password-1');
    await expect(page.getByRole('main').getByText('Five wrong tries pause password sign-in for 15 minutes.', { exact: false })).toBeVisible();
    await signIn('pw-locky-demo-2026');
    await signInThere();
  } finally {
    await other.close();
  }
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
  await withoutAutofill(page);
  await addVirtualAuthenticator(page);
  await addPasskey(page, 'alex', "Alex's test phone");
  await expect(page.getByText("Alex's test phone").first()).toBeVisible(); // the phone run left one too
  await logout(page);
  await page.goto('/login');
  await page.getByRole('button', { name: 'Sign in with a passkey' }).click();
  // Signed in, and on to the household's Home. '/' is only a stop on the way, there for as long as /me takes.
  await expect(page).toHaveURL(/\/b\/ours$/);
  expect((await page.request.get('/api/auth/me')).status()).toBe(200);
});

// Issue #13: the username box offers the passkey in its autofill. The virtual authenticator picks it as soon as Login
// asks, as a person would from the list under the box.
test('a passkey picked from the username box signs in without the button', async ({ page }) => {
  const device = await addVirtualAuthenticator(page);
  await addPasskey(page, 'alex', "Alex's autofill phone");
  await logout(page);
  expect(await held(device)).toHaveLength(1);
  await page.goto('/login');
  await expect(page).toHaveURL(/\/b\/ours$/);              // signed in, and on to the household's Home
  expect((await page.request.get('/api/auth/me')).status()).toBe(200);
});

// Issue #13: removing a passkey tells this device, which stops offering it. A device that missed that (another phone,
// here the same passkey put back) is refused in plain words when it offers the passkey, and told to forget it.
test('deleted passkey is refused in plain words, and the device forgets it', async ({ page }) => {
  await withoutAutofill(page);
  const device = await addVirtualAuthenticator(page);
  await addPasskey(page, 'spouse', 'Old phone');
  await expect(page.getByText('Old phone')).toBeVisible();
  const [passkey] = await held(device);
  await page.getByRole('button', { name: 'Remove Old phone' }).click();
  await page.getByRole('dialog', { name: 'Remove the passkey Old phone?' }).getByRole('button', { name: 'Remove' }).click();
  await expect(page.getByText('Removed the passkey Old phone.')).toBeVisible(); // the removal line says what went
  await expect(page.getByText('Old phone', { exact: true })).toHaveCount(0); // and the row is gone
  await expect(page.getByRole('button', { name: 'Remove Old phone' })).toHaveCount(0);
  await expect.poll(() => held(device)).toHaveLength(0);   // signalAllAcceptedCredentials reached the device
  await device.cdp.send('WebAuthn.addCredential', { authenticatorId: device.authenticatorId, credential: passkey });
  await logout(page);
  await page.goto('/login');
  await page.getByRole('button', { name: 'Sign in with a passkey' }).click();
  await expect(page.getByText("That passkey isn't registered any more. Sign in with your password and add it again.")).toBeVisible();
  await expect.poll(() => held(device)).toHaveLength(0);   // signalUnknownCredential did too
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
  await expect(page.getByRole('main').getByText('If that account exists, we sent a link. It works for 15 minutes.')).toBeVisible();
});

test('reset with a bad token says so', async ({ page }) => {
  await page.goto('/reset?token=not-a-real-token');
  await page.getByLabel('New password').fill('a-brand-new-password-1');
  await page.getByRole('button', { name: 'Change password' }).click();
  await expect(page.getByRole('main').getByText('That link has expired or was already used.')).toBeVisible();
  await expect(page.getByLabel('New password')).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Forgot your password?' })).toHaveAttribute('href', '/forgot');
});

test('reset with no token says to open the email link, with no form (issue 19)', async ({ page }) => {
  await page.goto('/reset');
  await expect(page.getByRole('main').getByText('Open this page from the link in your email.')).toBeVisible();
  await expect(page.getByLabel('New password')).toHaveCount(0);
  await page.getByRole('link', { name: 'Forgot your password?' }).click();
  await expect(page).toHaveURL(/\/forgot$/);
});
