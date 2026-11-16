import { expect, test, type Locator, type Page } from '@playwright/test';
import { animationsSettled, listView, loginAs, restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

test.beforeEach(async ({ page }) => { await loginAs(page, 'spouse'); await page.goto('/review'); });

const current = (page: Page) => page.locator('[data-testid=focus-card][data-role=current]');
const bar = (page: Page) => page.getByTestId('focus-bar');
const toast = (page: Page) => page.locator('.undo-toast');
const left = async (page: Page) => (await (await page.request.get('/api/b/ours/review')).json()).count as number;
const firstChip = (card: Locator) => card.locator('.chips button:not(.chip--more)').first();
/** Not the box test: leave the household's matching rows for it. */
async function untick(card: Locator) {
  const also = card.getByRole('checkbox', { name: /^Also the / });
  if (await also.count()) await also.uncheck();
}
/** Synthetic touch pointer events across the card: Playwright's mouse is a mouse, and focus swipes are touch only (P11). */
async function swipe(card: Locator, dx: number) {
  await card.evaluate((el, x) => {
    const r = el.getBoundingClientRect();
    const y = r.top + r.height / 2;
    const at = (type: string, cx: number) => el.dispatchEvent(new PointerEvent(type,
      { bubbles: true, cancelable: true, pointerId: 9, pointerType: 'touch', isPrimary: true, clientX: cx, clientY: y }));
    const x0 = r.left + r.width / 2;
    at('pointerdown', x0);
    at('pointermove', x0 + x / 2);
    at('pointermove', x0 + x);
    at('pointerup', x0 + x);
  }, dx);
}

test('focus is the default: the right button sorts, the toast says so, and the next card is already there', async ({ page }) => {
  await expect(page.getByRole('group', { name: 'View' }).getByRole('button', { name: 'Focus' })).toHaveAttribute('aria-pressed', 'true');
  const id = await current(page).getAttribute('data-id');
  const before = await left(page);
  await untick(current(page));
  const take = bar(page).getByRole('button').nth(1);
  const answered = page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().endsWith(`/transactions/${id}`));
  if ((await take.textContent())?.startsWith('All categories')) {
    await take.click();
    await page.getByRole('dialog', { name: 'Category' }).getByRole('option').first().click();
  } else {
    await take.click();
  }
  expect((await answered).ok()).toBeTruthy();
  await expect(toast(page)).toContainText('SORTED');
  await expect(current(page)).not.toHaveAttribute('data-id', id!);
  await expect.poll(() => left(page)).toBeLessThan(before);
});

test('Snooze from its button says when it comes back; Undo (Z on a desktop) returns the card', async ({ page }, testInfo) => {
  const id = await current(page).getAttribute('data-id');
  const before = await left(page);
  await bar(page).getByRole('button', { name: 'Snooze' }).click();
  await expect(toast(page)).toContainText(/Snoozed · back /);
  await expect(current(page)).not.toHaveAttribute('data-id', id!);
  expect(await left(page)).toBe(before - 1);
  if (testInfo.project.name === 'desktop') await page.keyboard.press('z');
  else await page.getByTestId('review-top').getByRole('button', { name: 'Undo' }).click();
  await expect(current(page)).toHaveAttribute('data-id', id!);
  await expect(current(page).getByText('Undone.')).toBeVisible();
  await expect.poll(() => left(page)).toBe(before);
});

test('touch swipes: left snoozes and Undo brings it back; right takes the guess or opens every category', async ({ page }) => {
  const a = await current(page).getAttribute('data-id');
  const snoozed = page.waitForResponse((r) => r.url().endsWith(`/review/${a}/snooze`));
  await swipe(current(page), -220);
  expect((await snoozed).ok()).toBeTruthy();
  await expect(current(page)).not.toHaveAttribute('data-id', a!);
  await page.getByTestId('review-top').getByRole('button', { name: 'Undo' }).click();
  await expect(current(page)).toHaveAttribute('data-id', a!);
  await untick(current(page));
  const guessed = !(await bar(page).getByRole('button').nth(1).textContent())?.startsWith('All categories');
  if (guessed) {
    const sorted = page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().endsWith(`/transactions/${a}`));
    await swipe(current(page), 220);
    expect((await sorted).ok()).toBeTruthy();
    await expect(current(page)).not.toHaveAttribute('data-id', a!);
    await page.getByTestId('review-top').getByRole('button', { name: 'Undo' }).click();      // leave the vault as it was
    await expect(current(page)).toHaveAttribute('data-id', a!);
  } else {
    await swipe(current(page), 220);
    await expect(page.getByRole('dialog', { name: 'Category' })).toBeVisible();
  }
});

test('list view: a sorted card leaves a slim row, and the card below keeps its place on screen', async ({ page }) => {
  await listView(page);
  const cards = page.locator('[data-testid=review-card]');
  await expect(cards.nth(7)).toBeVisible();
  // A card well down the page, so there is room to scroll by what it loses (P20).
  const card = cards.nth(6);
  const id = await card.getAttribute('data-id');
  await card.evaluate((el) => { el.scrollIntoView({ block: 'center' }); });
  const belowId = await page.evaluate((fid) => {
    const els = [...document.querySelectorAll<HTMLElement>('.rcards > [data-id]')];
    const me = els.find((e) => e.dataset.id === fid)!;
    const bottom = me.getBoundingClientRect().bottom;
    return els.find((e) => e !== me && e.getBoundingClientRect().top >= bottom - 1)?.dataset.id ?? null;
  }, id);
  expect(belowId, 'a row below the card').not.toBeNull();
  const below = page.locator(`.rcards > [data-id="${belowId}"]`);
  const top0 = (await below.boundingBox())!.y;
  await untick(card);
  await firstChip(card).click();
  const slim = page.locator(`[data-testid=slim-row][data-id="${id}"]`);
  await expect(slim).toContainText('SORTED ·');
  await animationsSettled(page);
  expect(Math.abs((await below.boundingBox())!.y - top0)).toBeLessThanOrEqual(1);
  await slim.getByRole('button', { name: 'Undo' }).click();
  await expect(page.locator(`[data-testid=review-card][data-id="${id}"]`)).toBeVisible();
});

test('the view is remembered after a reload', async ({ page }) => {
  await listView(page);
  await page.reload();
  await expect(page.getByRole('group', { name: 'View' }).getByRole('button', { name: 'List' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('[data-testid=review-card]').first()).toBeVisible();
  await page.getByRole('group', { name: 'View' }).getByRole('button', { name: 'Focus' }).click();
  await page.reload();
  await expect(current(page)).toBeVisible();
});

test('offline, a tap leaves the card and says so', async ({ page, context }) => {
  const id = await current(page).getAttribute('data-id');
  await context.setOffline(true);
  await firstChip(current(page)).click();
  await expect(current(page).getByText(/^Not saved\. Steward couldn't reach your home server\./)).toBeVisible();
  await context.setOffline(false);
  await page.reload();
  await expect(current(page)).toHaveAttribute('data-id', id!);
});

test('possible duplicates: keep both, or remove the file row', async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  const section = page.getByRole('region', { name: 'Possible duplicates' });
  // Wait for the real state, not for the clock: the page shows the pair, and the server counts it.
  const pairs = async () => (await (await page.request.get('/api/b/ours/review')).json()).duplicate_count as number;
  await expect(section).toBeVisible({ timeout: 15_000 });
  await expect(section.getByText('From the bank').first()).toBeVisible();
  await expect(section.getByText('From a file').first()).toBeVisible();
  const before = await pairs();
  expect(before).toBeGreaterThan(0);
  // The click is done when the server has answered it; then the count and the page follow.
  const answered = page.waitForResponse((r) => r.request().method() !== 'GET'
    && /\/(review\/duplicates\/keep|transactions\/\d+)$/.test(new URL(r.url()).pathname), { timeout: 15_000 });
  if (testInfo.project.name === 'phone') {
    await section.getByRole('button', { name: 'Remove this one' }).first().click();
    await page.getByRole('dialog', { name: 'Remove this transaction?' }).getByRole('button', { name: 'Remove' }).click();
  } else {
    await section.getByRole('button', { name: 'Keep both' }).first().click();
  }
  expect((await answered).ok()).toBeTruthy();
  await expect.poll(pairs, { timeout: 15_000 }).toBe(before - 1);
  if (before === 1) await expect(section).toBeHidden({ timeout: 15_000 });
});

test('everything sorted state', async ({ page }) => {
  await page.route('**/api/b/ours/review', (route) => route.fulfill({ json: { uncategorized: [], count: 0, duplicates: [], duplicate_count: 0, top_categories: [] } }));
  await page.reload();
  // Exact: the caughtUp pool's "All caught up. Go do something fun." can be drawn under the title (phase 17 spec 3.2).
  await expect(page.getByText('All caught up.', { exact: true })).toBeVisible();
});

test('the box applies to the rows like it, the slim row’s Undo puts them back, and unticked sorts only the one', async ({ page }) => {
  await listView(page);
  // The demo seed repeats SQ *VENDOR; its descriptions may carry a suffix.
  const list = '/api/b/ours/transactions?q=SQ%20*VENDOR&category=uncategorized&dates=all&limit=500';
  const q = await (await page.request.get('/api/b/ours/review')).json();
  const card = q.uncategorized.find((t: { raw_description: string; matching: number | null }) =>
    t.raw_description.startsWith('SQ *VENDOR') && (t.matching ?? 0) > 0);
  expect(card, 'the restored demo vault has a repeated unsorted SQ *VENDOR row').toBeTruthy();
  const before: number[] = q.uncategorized
    .filter((t: { raw_description: string }) => t.raw_description.startsWith('SQ *VENDOR')).map((t: { id: number }) => t.id);
  const ids = async () => ((await (await page.request.get(list)).json()).transactions as { id: number }[]).map((t) => t.id);
  const mine = page.locator(`[data-testid=review-card][data-id="${card.id}"]`);
  const slim = page.locator(`[data-testid=slim-row][data-id="${card.id}"]`);
  await mine.scrollIntoViewIfNeeded();
  const box = mine.getByRole('checkbox', { name: /^Also the (\d+|one) like it$/ });
  await expect(box).toBeChecked();
  await firstChip(mine).click();
  await expect(slim).toContainText(/like it as /);
  expect((await ids()).filter((id) => before.includes(id))).toEqual([]);
  await slim.getByRole('button', { name: 'Undo' }).click();
  await expect(mine.getByText('Undone.')).toBeVisible();
  const back = await ids();
  expect(before.filter((id) => !back.includes(id))).toEqual([]);
  await box.uncheck();
  await firstChip(mine).click();
  await expect(slim).toContainText(' as ');
  await expect(slim).not.toContainText('like it');
  const after = await ids();
  expect(before.filter((id) => id !== card.id && !after.includes(id))).toEqual([]);
  expect(after).not.toContain(card.id);
});

test('every card says why it is here', async ({ page }) => {
  await listView(page);
  const cards = page.locator('[data-testid=review-card]');
  await expect(cards.first()).toBeVisible();
  for (const c of (await cards.all()).slice(0, 5)) await expect(c.locator('.rcard__reason')).toHaveText(/Steward|payment/);
});
