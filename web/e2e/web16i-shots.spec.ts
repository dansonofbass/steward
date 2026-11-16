import { expect, test, type Page } from '@playwright/test';
import { animationsSettled, chatOn, restoreVault, tab } from './fixtures';
import { open, signIn, THEMES } from './open-screen';
import { DEMO_PORT } from './ports';

declare const process: { env: Record<string, string | undefined> };

// Fix 16i's screenshot gate (release gate 0.1.0): the screens the web platform fixes changed, in each project's dark
// then light. A form sheet and Ask's panel open, the discard question, focus on the new page's h1 after a page change,
// a field error after a failed save, a copy's note, and the Undo toast inside a sheet. Runs only with SHOTS_16I=1;
// files go to SHOTS_16I_DIR (default e2e/screenshots-16i/, gitignored).

const OUT = process.env.SHOTS_16I_DIR ?? 'e2e/screenshots-16i';
const AT = `http://localhost:${DEMO_PORT}`;

test.skip(!process.env.SHOTS_16I, 'set SHOTS_16I=1 to take fix 16i\'s screenshots');
test.beforeAll(async () => { await restoreVault(); });

async function shoot(page: Page, mode: string, name: string) {
  await page.evaluate(async () => { await document.fonts.ready; });
  await animationsSettled(page);
  await page.screenshot({ path: `${OUT}/${mode}/${name}.png` });
}

async function at(page: Page, url: string, theme: string, phase: string) {
  await open(page, `${AT}${url}`, theme, phase);
}

for (const [theme, phase] of THEMES) {
  test(`fix 16i's screens, ${theme}`, async ({ page, context }, info) => {
    test.setTimeout(120_000);
    const mode = `${info.project.name}-${theme}`;
    const phone = info.project.name === 'phone';
    await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: AT });
    await signIn(page, AT);
    await page.goto(`${AT}/api/health`);

    // A form sheet, then the question when Escape would discard what was typed.
    await at(page, '/b/ours/accounts', theme, phase);
    await page.getByRole('button', { name: 'Add an account' }).click();
    await page.getByRole('button', { name: /One you update manually/ }).click();
    const sheet = page.getByRole('dialog', { name: 'Add account' });   // the form's title, once it swaps in
    await expect(sheet.getByLabel('Name')).toBeVisible();
    await shoot(page, mode, '1-form-sheet');
    await sheet.getByLabel('Name').fill('Lake cabin fund');
    await page.keyboard.press('Escape');
    await expect(sheet.getByRole('button', { name: 'Keep editing' })).toBeFocused();
    await shoot(page, mode, '2-discard-question');
    // A second Escape never loses the text (16i review I-1). Where the browser lets it be stopped it means Keep editing;
    // where it can't be (Chromium with no activation in between), the sheet comes back still asking.
    await page.evaluate(() => {
      const w = window as unknown as { cancels: boolean[] };
      w.cancels = [];
      document.querySelector('dialog')!.addEventListener('cancel', (e) => w.cancels.push(e.cancelable), { capture: true });
    });
    await page.keyboard.press('Escape');
    await expect(sheet).toBeVisible();
    await expect(sheet.getByLabel('Name')).toHaveValue('Lake cabin fund');
    const [cancelable] = await page.evaluate(() => (window as unknown as { cancels: boolean[] }).cancels);
    console.log(`16I second Escape: cancelable=${cancelable}`);
    if (cancelable) await expect(sheet.getByLabel('Name')).toBeFocused();
    else await expect(sheet.getByRole('button', { name: 'Keep editing' })).toBeFocused();
    await shoot(page, mode, '2b-second-escape');
    if (cancelable) await page.keyboard.press('Escape');      // back to the question, to leave by Discard
    await sheet.getByRole('button', { name: 'Discard' }).click();
    await expect(sheet).toHaveCount(0);

    // Ask's panel, open on a category.
    await chatOn(page, 'ours');
    const { month } = (await (await page.request.get(`${AT}/api/b/ours/spending`)).json()) as { month: string };
    await at(page, `/b/ours/spending/dining?month=${month}`, theme, phase);
    await page.getByRole('button', { name: 'Ask about Eating out' }).click();
    await expect(page.getByRole('dialog', { name: 'Ask' })).toBeVisible();
    await shoot(page, mode, '3-ask-panel');
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog', { name: 'Ask' })).toHaveCount(0);

    // A page change by keyboard: focus lands on the new page's h1, with its ring.
    await at(page, '/b/ours', theme, phase);
    await tab(page, 'Spending').focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('main h1').first()).toBeFocused();
    await expect(page).toHaveTitle('Spending · Steward');
    await shoot(page, mode, '4-route-focus-h1');

    // A failed save: focus on the first field in error, its error tied to it.
    await at(page, '/b/ours/spending/setasides/new', theme, phase);
    await page.getByTestId('sa-form').locator('button[type=submit]').click();
    const first = page.locator('[aria-invalid="true"]').first();
    await expect(first).toBeFocused();
    await shoot(page, mode, '5-field-error');

    // A copy's note, on Get Steward ready's address line (made to need the line, as public-shots does).
    await page.route('**/api/b/ours/ready*', async (route) => {
      const body = await (await route.fetch()).json();
      body.rows = body.rows.map((r: { key: string }) => r.key !== 'address' ? r : { ...r, status: 'needs', go: 'Check again', detail: 'Steward is at http://localhost:8441.',
        lines: [{ name: 'STEWARD_BASE_URL', line: 'STEWARD_BASE_URL=https://steward.example.ts.net', running: 'http://localhost:8441', note: null, where: 'steward' }] });
      body.need = 1;
      await route.fulfill({ json: body });
    });
    await at(page, '/b/ours/settings/ready', theme, phase);
    await page.getByRole('button', { name: /Secure address/ }).click();
    // Exact: a row behind the phone's sheet has "copy" in its name, and the page behind a modal is inert.
    await page.getByRole('button', { name: 'Copy', exact: true }).first().click();
    await expect(page.getByRole('status').filter({ hasText: 'Copied' })).toBeVisible();
    await shoot(page, mode, '6-copy-note');
    await page.unroute('**/api/b/ours/ready*');

    // The Undo toast after a note is saved: inside the transaction's sheet on a phone, beside the pane on a desktop.
    await at(page, '/b/ours/transactions?q=DISNEYPLUS&dates=all', theme, phase);
    await page.getByTestId('txn-row').first().click();
    await page.getByTestId('note-form').waitFor();
    await page.getByLabel('Name').fill(`Disney+ ${theme}`);
    await page.getByTestId('note-form').getByRole('button', { name: 'Save' }).click();
    const toast = page.locator('.undo-toast');
    await expect(toast).toBeVisible();
    if (phone) await expect(page.getByRole('dialog').locator('.live-toasts .undo-toast')).toBeVisible();
    await shoot(page, mode, '7-undo-toast-in-sheet');
  });
}
