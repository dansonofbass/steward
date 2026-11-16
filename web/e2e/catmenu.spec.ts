import { expect, test, type Page } from '@playwright/test';
import { listView, loginAs, restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

// The category menu never scrolls sideways (JR, Oct 28): on a desktop, two columns of rows that wrap inside a menu
// about 320 px wide, clamped to the window, your usual first; on a phone, the half sheet with one column. Opened from
// More… on a Review card in each column of the grid (so the right-edge clamp runs) and from the detail's Category.

/** The open menu: the desktop popover, or the phone sheet (a modal <dialog>). */
const menuOf = (page: Page, phone: boolean) => page.locator(phone ? 'dialog.catmenu-sheet' : '.catmenu-pop');

async function checkMenu(page: Page, phone: boolean, where: string) {
  const menu = menuOf(page, phone);
  const list = menu.getByRole('listbox');
  await expect(list).toBeVisible();
  const usual = list.getByRole('group', { name: 'Your usual' });
  await expect(usual.getByRole('option').first()).toBeVisible();
  // The phone sheet slides up: measure once it has stopped moving.
  let was = '';
  await expect.poll(async () => {
    const now = JSON.stringify(await menu.boundingBox());
    const still = now === was;
    was = now;
    return still;
  }, { intervals: [100] }).toBe(true);

  const box = (await menu.boundingBox())!;
  const listBox = (await list.boundingBox())!;
  const vw = page.viewportSize()!.width;
  expect(box.x, `${where}: inside the window`).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width, `${where}: inside the window`).toBeLessThanOrEqual(vw + 0.5);
  if (!phone) {
    expect(box.width, `${where}: about 320 px`).toBeGreaterThanOrEqual(300);
    expect(box.width, `${where}: about 320 px`).toBeLessThanOrEqual(340);
  }

  const m = await list.evaluate((l) => ({ sw: l.scrollWidth, cw: l.clientWidth, x: getComputedStyle(l).overflowX }));
  expect(m.sw, `${where}: no sideways scroll`).toBeLessThanOrEqual(m.cw);
  expect(m.x).toBe('hidden');

  // Every row sits between the list's left and right edges, and your usual's rows are in view.
  const rows = await list.getByRole('option').evaluateAll((os) => os.map((o) => {
    const r = o.getBoundingClientRect();
    return { name: o.textContent, left: r.left, right: r.right, top: r.top, bottom: r.bottom, usual: !!o.closest('.catmenu__group--usual') };
  }));
  expect(rows.length).toBeGreaterThan(20);
  for (const r of rows) {
    expect(r.left, `${where}: ${r.name}`).toBeGreaterThanOrEqual(listBox.x - 0.5);
    expect(r.right, `${where}: ${r.name}`).toBeLessThanOrEqual(listBox.x + listBox.width + 0.5);
  }
  // All of your usual on a desktop; on a phone the 44 px rows run on below the sheet's fold, so the first.
  for (const r of rows.filter((x) => x.usual).slice(0, phone ? 1 : undefined)) {
    expect(r.top, `${where}: ${r.name}`).toBeGreaterThanOrEqual(listBox.y - 0.5);
    expect(r.bottom, `${where}: ${r.name}`).toBeLessThanOrEqual(listBox.y + listBox.height + 0.5);
  }
  // Two columns of rows on a desktop, one on a phone (the groups' rows; your usual's are the same).
  const columns = new Set(rows.map((r) => Math.round(r.left)));
  expect(columns.size, where).toBe(phone ? 1 : 2);

  // The arrow keys still reach the last row, which scrolls into view down the list, never sideways.
  await page.keyboard.press('ArrowUp');
  const last = list.getByRole('option').last();
  await expect(last).toHaveClass(/is-active/);
  await expect.poll(() => last.evaluate((o) => {
    const l = o.closest('[role=listbox]')!.getBoundingClientRect();
    const r = o.getBoundingClientRect();
    return r.top >= l.top - 0.5 && r.bottom <= l.bottom + 0.5;
  })).toBe(true);
  expect(await list.evaluate((l) => l.scrollLeft)).toBe(0);

  await page.keyboard.press('Escape');
  await expect(list).toHaveCount(0);
}

test.beforeEach(async ({ page }) => { await loginAs(page, 'spouse'); });

test('the category menu fits its width: two columns on a desktop, one on a phone, never a sideways scroll', async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  const phone = testInfo.project.name === 'phone';
  for (const width of phone ? [0] : [1280, 1024]) {
    if (width) await page.setViewportSize({ width, height: 800 });
    const at = phone ? 'phone' : String(width);
    await page.goto('/review');
    await listView(page);
    const mores = page.getByRole('button', { name: /^More/ });
    await expect(mores.first()).toBeVisible();
    // The first More… in each column of the card grid: left, middle and right on a wide desktop.
    const seen = new Set<number>();
    const picks: number[] = [];
    for (let i = 0; i < Math.min(await mores.count(), 6); i++) {
      const x = Math.round((await mores.nth(i).boundingBox())!.x);
      if (!seen.has(x)) { seen.add(x); picks.push(i); }
    }
    expect(picks.length).toBe(phone ? 1 : width >= 1280 ? 3 : 2);
    for (const i of picks) {
      await mores.nth(i).click();
      await checkMenu(page, phone, `${at} Review card ${i}`);
      await expect(mores.nth(i)).toBeFocused();
    }

    await page.goto('/transactions?dates=all');
    await page.locator('[data-testid=txn-row]').first().click();
    await page.getByTestId('txn-detail').getByRole('button', { name: /^Category / }).click();
    await checkMenu(page, phone, `${at} transaction detail`);
  }
});
