import { expect, test } from '@playwright/test';
import { listView, loginAs, restoreVault } from './fixtures';

// Issue #27: the desktop menus are native popovers, anchored to their triggers. The browser closes them on a press or
// a tap outside, and on Escape, and keeps them by their triggers as the window changes size.
test.beforeAll(async () => { await restoreVault(); });

test.beforeEach(async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === 'phone', 'the rail, the ⋯ menu and the category popover are desktop menus');
  await loginAs(page, 'spouse');
});

/** A tap on the page's own heading: outside every menu, and nothing happens there. */
const tapHeading = async (page: import('@playwright/test').Page) => {
  const h = (await page.getByRole('heading', { level: 1 }).first().boundingBox())!;
  await page.touchscreen.tap(h.x + 8, h.y + h.height / 2);
};

test.describe('on a touch laptop', () => {
  test.use({ hasTouch: true });   // a mouse, and a screen to tap

  test('a tap outside closes the You menu, and so does Escape, giving focus back', async ({ page }) => {
    await page.goto('/');
    const you = page.getByRole('button', { name: /^You: / });
    const menu = page.getByRole('dialog', { name: await you.locator('.you__name').innerText() });
    await you.click();
    await expect(menu).toBeVisible();
    // Above the button, as wide as it.
    const [b, m] = [(await you.boundingBox())!, (await menu.boundingBox())!];
    expect(m.y + m.height).toBeLessThanOrEqual(b.y + 0.5);
    expect(m.x).toBeCloseTo(b.x, 0);
    expect(m.width).toBeCloseTo(b.width, 0);
    await tapHeading(page);
    await expect(menu).toBeHidden();
    await expect(you).toHaveAttribute('aria-expanded', 'false');

    await you.click();
    await expect(menu).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(menu).toBeHidden();
    await expect(you).toBeFocused();
    await you.click();
    await you.click();          // the button closes what it opened; a press on it never counts as outside
    await expect(menu).toBeHidden();
  });

  test('a tap outside closes the ⋯ menu on a Focus card', async ({ page }) => {
    await page.goto('/review');
    const card = page.locator('[data-testid=focus-card][data-role=current]');
    const dots = card.getByRole('button', { name: 'More actions' });
    await dots.click();
    const list = page.getByRole('menu', { name: 'More actions' });
    await expect(list).toBeVisible();
    await expect(list.getByRole('menuitem').first()).toBeFocused();
    // Under ⋯, by its end edge.
    const [d, l] = [(await dots.boundingBox())!, (await list.boundingBox())!];
    expect(l.y).toBeGreaterThanOrEqual(d.y + d.height);
    expect(l.x + l.width).toBeCloseTo(d.x + d.width, 0);
    await tapHeading(page);
    await expect(list).toBeHidden();
    await expect(dots).toHaveAttribute('aria-expanded', 'false');
  });
});

test('the category menu stays by its trigger as the window changes size, and a press outside closes it', async ({ page }) => {
  await page.goto('/review');
  await listView(page);
  const more = page.getByRole('button', { name: /^More/ }).first();
  await more.click();
  const menu = page.locator('.catmenu-pop');
  await expect(menu.getByRole('listbox')).toBeVisible();
  await expect(menu.getByRole('combobox')).toBeFocused();
  const by = async () => {
    const [t, m] = [(await more.boundingBox())!, (await menu.boundingBox())!];
    return { under: Math.abs(m.y - (t.y + t.height + 4)) <= 1, over: Math.abs(m.y + m.height - (t.y - 4)) <= 1, left: m.x, tLeft: t.x, right: m.x + m.width };
  };
  for (const size of [{ width: 1280, height: 800 }, { width: 1000, height: 760 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(size);
    await expect.poll(async () => { const p = await by(); return p.under || p.over; }, { message: `${size.width}: by its trigger` }).toBe(true);
    const p = await by();
    expect(p.right, `${size.width}: inside the window`).toBeLessThanOrEqual(size.width + 0.5);
    expect(p.left, `${size.width}: inside the window`).toBeGreaterThanOrEqual(0);
  }
  await page.getByRole('heading', { level: 1 }).first().click({ position: { x: 8, y: 8 } });
  await expect(menu).toHaveCount(0);
  await more.click();
  await expect(menu.getByRole('listbox')).toBeVisible();
  await more.click();          // its trigger closes it, as before
  await expect(menu).toHaveCount(0);
});

