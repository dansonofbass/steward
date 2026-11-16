import { expect, test, type Page } from '@playwright/test';
import { CHAT_PW, chatOn, GATEWAY, loginAs, restoreVault, tab, waitForGateway } from './fixtures';

// Spec 2026-11-05, section 7: server.sh runs the demo with STEWARD_GATEWAY_NAME=Zebra-Box, so Home, Import, Chat and
// Settings say Zebra-Box, and no page shows the {gateway} slot unfilled.
const NAME = 'Zebra-Box';
const who = (project: string) => `cass-${project}`;
const noSlot = async (page: Page) => expect(await page.content()).not.toContain('{gateway}');

test.beforeAll(async () => { await restoreVault(); });
test.afterEach(async ({ page, request }) => {
  await request.post(`${GATEWAY}/__e2e/reset`);
  await waitForGateway(page, 'ours', (s) => s.gateway.state === 'ok');
});

test('/me carries the name', async ({ page }) => {
  await loginAs(page, 'alex');
  expect((await (await page.request.get('/api/auth/me')).json()).gateway_name).toBe(NAME);
});

test('Settings and Chat name it, answering and away', async ({ page, request }, info) => {
  await loginAs(page, who(info.project.name), CHAT_PW);
  await chatOn(page, 'ours');
  await page.goto('/b/ours/settings/chat');
  await expect(page.getByRole('heading', { name: NAME, exact: true })).toBeVisible();
  await expect(page.getByText(`${NAME} is answering`)).toBeVisible();
  await expect(page.getByText(`PDFs are read on ${NAME}`)).toBeVisible();
  await noSlot(page);
  await request.post(`${GATEWAY}/__e2e/away`, { data: { away: true } });
  await waitForGateway(page, 'ours', (s) => s.gateway.state === 'away');
  await page.goto('/b/ours');
  await tab(page, 'Ask').click();
  await expect(page.getByRole('heading', { name: `Chat needs ${NAME}` })).toBeVisible();
  await expect(page.getByLabel('Your question')).toHaveAttribute('placeholder', `Paused until ${NAME} answers`);
  await noSlot(page);
});

test('Home says it is waiting for it', async ({ page }) => {
  await loginAs(page, 'alex');
  await page.route(/\/api\/b\/ours\/review$/, async (route) => {
    const res = await route.fetch();
    await route.fulfill({ response: res, json: { ...(await res.json()), background: { pending: 14, done: 0, waiting: true } } });
  });
  await page.goto('/b/ours');
  await expect(page.getByTestId('background-line')).toContainText(`Waiting for ${NAME} to categorize 14`);
  await noSlot(page);
});

test('Import says a statement waits for it', async ({ page }) => {
  await loginAs(page, 'alex');
  const line = { id: 901, name: 'march.pdf', bytes: 120_000, pages: 2, added_by: 'Alex', kind: 'text', state: 'waiting',
    error: null, error_text: null, label: null, statement_kind: null, period: null, rows: null, holdings: null,
    balance_cents: null, gap_cents: null, anyway: false, progress: null, last4: null, account_id: null,
    suggested_by: null, imported_before: null, expires_at: '2026-12-31T00:00:00Z', removed: false };
  await page.route(/\/api\/b\/ours\/import\/statements$/, (r) => r.fulfill({ json: { statements: [line], gateway: 'answering', reading: 'gateway' } }));
  await page.goto('/b/ours/settings/import');
  await expect(page.getByText(`Waiting for ${NAME}`)).toBeVisible();
  await noSlot(page);
});
