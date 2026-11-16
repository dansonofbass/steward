import { expect, test, type Locator, type Page } from '@playwright/test';
import { loginAs, monthEnd, restoreVault, serverDay, statementPdf } from './fixtures';
import { DEMO_PORT, GATEWAY_PORT } from './ports';

declare const process: { env: Record<string, string | undefined> };
const TASK = process.env.SHOTS_TASK;
const SIZES = [['1280x800', { width: 1280, height: 800 }], ['390x844', { width: 390, height: 844 }]] as const;
const PART = TASK === '7' || TASK === '8' || TASK === 'final-fix' ? 3 : TASK === '6' ? 2 : 1;
const OUT = TASK === 'remote' ? '../.superpowers/sdd/2026-11-02-steward-pdf-remote/shots/task-5'
  : `../.superpowers/sdd/2026-11-01-steward-pdf-${PART}/shots/${TASK === 'final-fix' ? TASK : `task-${TASK}`}`;
const BY_TASK: Record<string, string[]> = { '9': ['lines'], '10': ['lines', 'layout', 'review', 'done'], '6': ['scan'], '7': ['holdings'], '8': ['holdings'],
  'final-fix': ['final'], remote: ['pdf-place'] };

/** Both themes at the size the page already has: a resize remounts the screen and loses an open line, so the whole
 *  flow runs once per size and only the theme changes under it. */
async function shoot(page: Page, state: string, label: string, into?: Locator) {
  for (const theme of ['light', 'dark'] as const) {
    await page.evaluate((t) => { localStorage.setItem('steward-theme', t); document.documentElement.dataset.phase = t === 'dark' ? 'night' : 'day'; }, theme);
    await page.waitForLoadState('networkidle');
    await page.evaluate(() => Promise.all([document.fonts.ready, ...document.getAnimations().map((a) => a.finished.catch(() => null))]));
    expect(await page.evaluate(() => [...document.querySelectorAll('body *')].filter((e) => e.getBoundingClientRect().right > document.documentElement.clientWidth + 0.5 && !e.closest('.table-wrap')).slice(0, 8).map((e) => `${e.tagName}.${e.className}:${Math.round(e.getBoundingClientRect().right)}/${document.documentElement.clientWidth}/${document.documentElement.scrollWidth}`))).toEqual([]);
    // Nothing may scroll the page sideways; a table scrolls inside its own wrap. The offenders show in the failure.
    expect(await page.evaluate(() => (document.documentElement.scrollWidth <= document.documentElement.clientWidth ? [] :
      [...document.querySelectorAll('body *')].filter((e) => e.getBoundingClientRect().right > document.documentElement.clientWidth + 0.5 && !e.closest('.table-wrap'))
        .slice(0, 8).map((e) => `${e.tagName}.${e.className}:${Math.round(e.getBoundingClientRect().right)}/${document.documentElement.clientWidth}`)))).toEqual([]);
    if (into) await into.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${OUT}/${state}-${label}-${theme}.png` });
  }
}

test('a scan in row review', async ({ browser }) => {
  test.skip(!TASK || !BY_TASK[TASK].includes('scan'), 'SHOTS_TASK picks the states to shoot');
  test.setTimeout(300_000);
  for (const [label, viewport] of SIZES) {
    await restoreVault();
    const ctx = await browser.newContext({ viewport, baseURL: `http://localhost:${DEMO_PORT}` });
    const page = await ctx.newPage();
    await loginAs(page, 'alex');
    const day = await serverDay(page);
    const end = monthEnd(day, 1);
    await page.request.post(`http://127.0.0.1:${GATEWAY_PORT}/__e2e/scan-truth`, { data: { sid: 'boa_checking', end, slip: 900 } });
    await page.goto('/settings/import');
    await page.locator('input[type=file]').setInputFiles([await statementPdf(page, 'scan_0042.pdf', 'boa_checking', end, 'scan')]);
    await page.getByRole('button', { name: 'Off by $9.00 · Check rows' }).click();
    await page.getByText('Descriptions read from a scan · check them').waitFor();
    await page.locator('.imp-st__scan').first().waitFor();
    await shoot(page, 'scan', label);
    await ctx.close();
  }
});

test('statement lines', async ({ browser }) => {
  test.skip(!TASK || !BY_TASK[TASK].some((s) => ['lines', 'layout', 'review', 'done'].includes(s)), 'SHOTS_TASK picks the states to shoot');
  test.setTimeout(300_000);
  for (const [label, viewport] of SIZES) {
    await restoreVault();
    const ctx = await browser.newContext({ viewport, baseURL: `http://localhost:${DEMO_PORT}` });
    const page = await ctx.newPage();
    await loginAs(page, 'alex');
    const day = await serverDay(page);
    // New accounts, so SimpleFIN has nothing to skip the rows against (made before the page loads its account list).
    const mine = async (name: string, type: string) => String((await (await page.request.post('/api/b/ours/accounts',
      { data: { name, type, owner: 'joint', balance_cents: 0 } })).json()).id);
    const checking = await mine(`Shots checking ${label}`, 'checking');
    const card = await mine(`Shots card ${label}`, 'credit');
    await page.goto('/settings/import');
    await page.locator('input[type=file]').setInputFiles([
      await statementPdf(page, 'Statement_checking.pdf', 'chase_checking', monthEnd(day, 1)),
      await statementPdf(page, 'eStmt_card.pdf', 'chase_card', monthEnd(day, 1)),
      await statementPdf(page, 'Stmt_off.pdf', 'boa_checking', monthEnd(day, 1), 'off'),
      await statementPdf(page, 'protected.pdf', 'citi_card', monthEnd(day, 1), 'password'),
    ]);
    await expect(page.getByRole('button', { name: 'Check the layout · 1 look' })).toHaveCount(2);
    await expect(page.getByText('This PDF has a password. Save a copy without one and try again.', { exact: true })).toBeVisible();
    if (BY_TASK[TASK!].includes('lines')) await shoot(page, 'lines', label, page.getByRole('button', { name: /^Preview/ }));
    if (BY_TASK[TASK!].includes('layout')) {
      await page.getByRole('button', { name: 'Check the layout · 1 look' }).first().click();
      await page.getByRole('button', { name: 'Looks right' }).first().waitFor();
      await shoot(page, 'layout', label);
      await page.getByRole('button', { name: 'Looks right' }).first().click();
    }
    if (BY_TASK[TASK!].includes('review')) {
      await page.getByRole('button', { name: /^Off by \$12\.40 · Check rows$/ }).click();
      await page.locator('.imp-st__gap').waitFor();   // the rows load after the line opens
      await shoot(page, 'review', label);
      const off = page.getByRole('button', { name: /^Off by \$12\.40 · Check rows$/ });
      if ((await off.getAttribute('aria-expanded')) !== 'true') await off.click();
      await page.getByLabel('Import anyway').check();
      await page.getByRole('button', { name: 'Done' }).click();
    }
    if (BY_TASK[TASK!].includes('done')) {
      // The joy line needs every imported statement to add up, so the one imported anyway leaves the batch first.
      await page.getByRole('button', { name: 'Remove Stmt_off.pdf' }).click();
      await expect(page.getByRole('button', { name: 'Remove Stmt_off.pdf' })).toHaveCount(0);   // the row has folded away
      await page.getByRole('button', { name: 'Check the layout · 1 look' }).first().click();
      await page.getByRole('button', { name: 'Looks right' }).first().click();
      await page.getByLabel('Account for Statement_checking.pdf').selectOption(checking);
      await page.getByLabel('Account for eStmt_card.pdf').selectOption(card);
      await expect(page.getByRole('button', { name: /^Preview/ })).toBeEnabled();      // enabled again once the account changes have settled
      await page.getByRole('button', { name: /^Preview/ }).click();
      await page.getByRole('button', { name: /^Import [\d,]+$/ }).click();
      await page.getByText('2 statements, every one adds up.').waitFor();
      await expect(page.locator('.undo-toast')).toHaveCount(1);         // the import's Undo, never under a Removed toast
      await expect(page.locator('.undo-toast')).toContainText(/^Imported/);
      await shoot(page, 'done', label);
    }
    await ctx.close();
  }
});

/** Task 7 (PR 3): every screen the holdings work changed, one flow per size. */
test('holdings and loans', async ({ browser }) => {
  test.skip(!TASK || !BY_TASK[TASK].includes('holdings'), 'SHOTS_TASK picks the states to shoot');
  test.setTimeout(300_000);
  for (const [label, viewport] of SIZES) {
    await restoreVault();
    const ctx = await browser.newContext({ viewport, baseURL: `http://localhost:${DEMO_PORT}` });
    const page = await ctx.newPage();
    await loginAs(page, 'alex');
    const day = await serverDay(page);
    const end = monthEnd(day, 1);
    const mine = async (name: string, type: string) => String((await (await page.request.post('/api/b/ours/accounts',
      { data: { name, type, owner: 'joint', balance_cents: 0 } })).json()).id);
    const ira = await mine(`Shots IRA ${label}`, 'traditional_ira');
    const brokerage = await mine(`Shots brokerage ${label}`, 'brokerage_taxable');
    const loan = await mine(`Shots mortgage ${label}`, 'mortgage');
    await page.goto('/settings/import');
    await page.locator('input[type=file]').setInputFiles([
      await statementPdf(page, 'IRA_Q1.pdf', 'vanguard_ira', end),
      await statementPdf(page, 'Brokerage_off.pdf', 'fidelity_brokerage', end, 'off'),
      await statementPdf(page, 'Mortgage.pdf', 'mortgage', end),
    ]);
    await page.getByLabel('Account for IRA_Q1.pdf').selectOption(ira);
    await page.getByLabel('Account for Brokerage_off.pdf').selectOption(brokerage);
    await page.getByLabel('Account for Mortgage.pdf').selectOption(loan);
    await page.getByRole('button', { name: 'Check the holdings · 1 look' }).first().click();
    await page.getByRole('button', { name: 'Looks right' }).first().waitFor();
    await expect(page.getByText('Holdings add up to the total ✓')).toBeVisible();
    await shoot(page, 'holdings', label, page.getByRole('button', { name: 'Looks right' }).first());
    await page.getByRole('button', { name: 'Looks right' }).first().click();
    await page.getByRole('button', { name: /^Off by \$[\d.]+ · Check rows$/ }).click();
    await page.getByText(/^Holdings are \$[\d.]+ short of the total$/).waitFor();
    await shoot(page, 'holdings-review', label, page.locator('.imp-st__gap'));
    await page.getByLabel('Import anyway').check();
    await page.getByRole('button', { name: 'Done' }).click();
    await page.getByRole('button', { name: 'Check the layout · 1 look' }).click();
    await page.getByText(/Principal \$/).waitFor();
    await shoot(page, 'loan', label, page.getByRole('button', { name: 'Looks right' }).first());
    await page.getByRole('button', { name: 'Looks right' }).first().click();
    await expect(page.getByRole('button', { name: /^Preview/ })).toBeEnabled();
    await page.getByRole('button', { name: /^Preview/ }).click();
    await page.getByText(/^Holdings \d statements?$/).waitFor();
    await shoot(page, 'preview', label);
    await page.getByRole('button', { name: /^Look: Holdings/ }).click();
    await page.getByRole('dialog', { name: 'Holdings' }).waitFor();
    await shoot(page, 'holdings-look', label);
    await page.getByRole('button', { name: 'Done' }).click();
    await page.getByRole('button', { name: /^Import [\d,]+$/ }).click();
    await page.getByText(/^Imported [\d,]+ into /).waitFor();
    await page.goto(`/accounts/${ira}`);
    await page.getByText(/^from Statement, \w{3} \d{4} \(PDF\)$/).waitFor();
    await shoot(page, 'investment', label, page.getByText(/^from Statement, /));
    await ctx.close();
  }
});

test('an Inventory item with holdings', async ({ browser }) => {
  test.skip(!TASK || !BY_TASK[TASK].includes('holdings'), 'SHOTS_TASK picks the states to shoot');
  test.setTimeout(300_000);
  for (const [label, viewport] of SIZES) {
    await restoreVault();
    const ctx = await browser.newContext({ viewport, baseURL: `http://localhost:${DEMO_PORT}` });
    const page = await ctx.newPage();
    await loginAs(page, 'alex');
    const slug = 'margaret-ellis-seed-desktop';
    const end = monthEnd(await serverDay(page), 1);
    const items = (await (await page.request.get(`/api/b/${slug}/inventory`)).json()).items as { id: number; kind: string; account_id: number | null }[];
    const item = items.find((i) => i.kind === 'account' && i.account_id !== null)!;
    await page.goto(`/b/${slug}/settings/import`);
    await page.locator('input[type=file]').setInputFiles([await statementPdf(page, 'IRA_Q1.pdf', 'vanguard_ira', end)]);
    await page.getByLabel('Account for IRA_Q1.pdf').selectOption(String(item.account_id));
    await page.getByRole('button', { name: 'Check the holdings · 1 look' }).click();
    await page.getByRole('button', { name: 'Looks right' }).click();
    await page.getByRole('button', { name: 'Preview' }).click();
    await page.getByRole('button', { name: /^Import [\d,]+$/ }).click();
    await page.getByText(/^Imported [\d,]+ into /).waitFor();
    await page.goto(`/b/${slug}/inventory/${item.id}`);
    await page.getByRole('heading', { name: /^Holdings on / }).waitFor();
    await shoot(page, 'inventory', label, page.getByRole('heading', { name: /^Holdings on / }));
    await ctx.close();
  }
});

/** PR 3's final fixes: a holdings statement on a checking account (its note), then a same-day pair's preview. */
test('the type note and a same-day pair', async ({ browser }) => {
  test.skip(!TASK || !BY_TASK[TASK].includes('final'), 'SHOTS_TASK picks the states to shoot');
  test.setTimeout(300_000);
  for (const [label, viewport] of SIZES) {
    await restoreVault();
    const ctx = await browser.newContext({ viewport, baseURL: `http://localhost:${DEMO_PORT}` });
    const page = await ctx.newPage();
    await loginAs(page, 'alex');
    const end = monthEnd(await serverDay(page), 1);
    const mine = async (name: string, type: string) => String((await (await page.request.post('/api/b/ours/accounts',
      { data: { name, type, owner: 'joint', balance_cents: 0 } })).json()).id);
    const ira = await mine(`Shots IRA ${label}`, 'traditional_ira');
    const checking = await mine(`Joint checking ${label}`, 'checking');
    const loan = await mine(`Shots mortgage ${label}`, 'mortgage');
    await page.goto('/settings/import');
    await page.locator('input[type=file]').setInputFiles([
      await statementPdf(page, 'IRA_Q1.pdf', 'vanguard_ira', end),
      await statementPdf(page, 'Brokerage.pdf', 'fidelity_brokerage', end),
      await statementPdf(page, 'Mortgage.pdf', 'mortgage', end),
    ]);
    await page.getByLabel('Account for IRA_Q1.pdf').selectOption(ira);
    await page.getByLabel('Account for Brokerage.pdf').selectOption(checking);
    await page.getByLabel('Account for Mortgage.pdf').selectOption(loan);
    const note = page.getByText(`Joint checking ${label} isn't an investment account. Holdings usually go on one.`);
    await note.waitFor();
    await expect(page.getByRole('button', { name: 'Check the holdings · 1 look' })).toHaveCount(2);
    await shoot(page, 'note', label, note);
    for (const [file, tag] of [['Brokerage.pdf', 'Check the holdings · 1 look'], ['IRA_Q1.pdf', 'Check the holdings · 1 look'],
      ['Mortgage.pdf', 'Check the layout · 1 look']]) {
      const line = page.locator('li.imp-row', { hasText: file });
      await line.getByRole('button', { name: tag }).click();
      await line.getByRole('button', { name: 'Looks right' }).click();
      await expect(line.getByRole('button', { name: tag })).toHaveCount(0);       // settled before the next line opens
    }
    await page.getByLabel('Account for Brokerage.pdf').selectOption(ira);          // the same account and day as the IRA's
    await expect(note).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^Preview/ })).toBeEnabled();
    await page.getByRole('button', { name: /^Preview/ }).click();
    await page.getByText('Balances 3 · 1 kept').waitFor();
    await expect(page.getByText(/^Holdings for \w{3} \d+ already in Steward · kept$/)).toBeVisible();
    await shoot(page, 'preview', label, page.getByRole('button', { name: /^Import [\d,]+$/ }));
    await ctx.close();
  }
});

test('where PDFs are read, on Settings › Chat', async ({ browser }) => {
  test.skip(!TASK || !BY_TASK[TASK].includes('pdf-place'), 'SHOTS_TASK picks the states to shoot');
  test.setTimeout(300_000);
  for (const [label, viewport] of SIZES) {
    await restoreVault();
    const ctx = await browser.newContext({ viewport, baseURL: `http://localhost:${DEMO_PORT}` });
    const page = await ctx.newPage();
    await loginAs(page, 'alex');
    await page.goto('/b/ours/settings/chat');
    const line = page.getByText('PDFs are read on Zebra-Box');
    await line.waitFor();
    await shoot(page, 'pdf-place', label, line);
    await ctx.close();
  }
});
