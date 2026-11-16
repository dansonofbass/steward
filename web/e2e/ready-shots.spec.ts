import { test, type Page } from '@playwright/test';
import { animationsSettled, loginAs, restoreVault } from './fixtures';
import { DEMO_PORT } from './ports';

// The screenshot gate for the Get Steward ready tasks (8, 9, 10, and 'final' for the final fix round): set SHOTS_TASK to the task's number.
declare const process: { env: Record<string, string | undefined> };
const TASK = process.env.SHOTS_TASK;
const SIZES = [['390x844', { width: 390, height: 844 }], ['1280x800', { width: 1280, height: 800 }]] as const;
const GPU = TASK === 'gpu-6'; // the GPU pathway plan's Task 6: the Ask panel's "Runs on" line
const OUT = GPU ? '../.superpowers/sdd/2026-11-09-steward-gateway-gpu/shots/task-6' : `../.superpowers/sdd/2026-11-08-steward-guided-setup-a/shots/task-${TASK}`;
const BY_TASK: Record<string, string[]> = { '8': ['page', 'address', 'plan-checklist'], '9': ['email', 'ask', 'chat-pair'], '10': ['page', 'email', 'ask', 'chat-pair'], final: ['ask-away'],
  'gpu-6': ['ask-cpu', 'ask-cuda'] };

async function state(page: Page, name: string): Promise<boolean> {
  if (name === 'plan-checklist') {
    await page.goto('/plan');
    await page.waitForLoadState('networkidle');
    return (await page.getByTestId('setup-row').count()) > 0; // the demo household may be past its checklist
  }
  if (name === 'address') {
    // The demo server's address is already fine, so this shot shows the state that needs the line (this shot only).
    await page.route('**/api/b/ours/ready*', async (route) => {
      const body = await (await route.fetch()).json();
      body.rows = body.rows.map((r: { key: string }) => r.key !== 'address' ? r : { ...r, status: 'needs', go: 'Check again', detail: 'Steward is at http://localhost:8441.',
        lines: [{ name: 'STEWARD_BASE_URL', line: 'STEWARD_BASE_URL=https://steward.example.ts.net', running: 'http://localhost:8441', note: null, where: 'steward' }] });
      body.need = 1;
      await route.fulfill({ json: body });
    });
  }
  if (name === 'ask-away') {
    // The fake gateway answers, so this shot shows a paired gateway that is away (this shot only).
    await page.route('**/api/b/ours/ready*', async (route) => {
      const body = await (await route.fetch()).json();
      body.rows = body.rows.map((r: { key: string; extra: object }) => r.key !== 'ask' ? r
        : { ...r, status: 'needs', go: 'Check again', detail: 'The gateway is away.', lines: [], extra: { ...r.extra, paired: true, url_set: true, state: 'away', chat_on: true } });
      body.need = 1;
      await route.fulfill({ json: body });
    });
  }
  if (name === 'ask-cpu' || name === 'ask-cuda') {
    // A paired gateway that answers, on the CPU or an NVIDIA GPU (these shots only).
    const accelerator = name === 'ask-cpu' ? 'cpu' : 'cuda';
    await page.route('**/api/b/ours/ready*', async (route) => {
      const body = await (await route.fetch()).json();
      body.rows = body.rows.map((r: { key: string; extra: object }) => r.key !== 'ask' ? r
        : { ...r, status: 'done', go: null, detail: 'The gateway is answering. Ask is on.', lines: [], extra: { ...r.extra, paired: true, url_set: true, state: 'ok', chat_on: true, accelerator } });
      await route.fulfill({ json: body });
    });
  }
  if (name === 'chat-pair') {
    // alex is paired in the demo vault, so this shot shows the unpaired state (this shot only; the vault is never unpaired).
    await page.route('**/api/b/ours/chat', async (route) => {
      const body = await (await route.fetch()).json();
      body.gateway = { ...body.gateway, state: 'not_set_up', line: 'Not paired.', paired: false, url_set: true };
      await route.fulfill({ json: body });
    });
    await page.goto('/settings/chat');
    await page.getByLabel('Code', { exact: true }).waitFor();
    return true;
  }
  await page.goto('/settings/ready');
  await page.getByRole('heading', { name: 'Get Steward ready', level: 2 }).waitFor();
  await page.getByTestId('ready-row').first().waitFor();
  if (name === 'address') await page.getByRole('button', { name: /Secure address/ }).click();
  if (name === 'email') { await page.getByRole('button', { name: /^Email/ }).click(); await page.getByLabel('Host').waitFor(); }
  if (name === 'ask-away') { await page.getByRole('button', { name: /^Ask/ }).click(); await page.getByRole('button', { name: 'Check again', exact: true }).waitFor(); }
  if (name === 'ask-cpu' || name === 'ask-cuda') { await page.getByRole('button', { name: /^Ask/ }).click(); await page.getByText(/^Runs on /).waitFor(); }
  if (name === 'ask') { await page.getByRole('button', { name: /^Ask/ }).click(); await page.getByRole('button', { name: 'Pair again' }).waitFor(); }
  return true;
}

test.describe('Get Steward ready screenshots (the gate for Tasks 8 to 10)', () => {
  test.skip(!TASK || !BY_TASK[TASK], 'set SHOTS_TASK to 8, 9, 10 or final');
  test.beforeAll(async () => { await restoreVault(); });
  test('each state at both sizes, dark first, phone first', async ({ browser }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'one run is enough');
    test.setTimeout(600_000);
    for (const name of BY_TASK[TASK!]) {
      for (const theme of ['dark', 'light'] as const) {
        for (const [size, viewport] of SIZES) {
          await restoreVault();
          const ctx = await browser.newContext({ viewport, baseURL: `http://localhost:${DEMO_PORT}` });
          await ctx.addInitScript((t) => { localStorage.setItem('steward-theme', t); }, theme);
          const page = await ctx.newPage();
          await loginAs(page, 'alex');
          if (await state(page, name)) {
            await animationsSettled(page);
            await page.screenshot({ path: `${OUT}/${name}-${size}-${theme}.png` });
          } else {
            console.log(`${name}: the demo household shows no checklist; no shot`);
          }
          await ctx.close();
        }
      }
    }
  });
});
