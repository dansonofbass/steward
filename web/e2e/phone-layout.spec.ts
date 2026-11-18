import { expect, test, type Page } from '@playwright/test';
import { loginAs, restoreVault } from './fixtures';

// #22: the Plan's and Spending's five tabs at phone width. The row stays one line (the fifth tab used to wrap onto a
// line of its own), scrolls sideways with a fade on the edge that has more, and the current tab is wholly in view.
// Nothing here writes; the vault is restored so the Plan is ready, as the demo seeds it.

test.beforeAll(async () => { await restoreVault(); });
test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name !== 'phone', 'a phone layout');
  await loginAs(page, 'alex');
});

async function row(page: Page, label: string) {
  const nav = page.getByRole('navigation', { name: label });
  await expect(nav.getByRole('link')).toHaveCount(5);
  return nav.evaluate((el) => {
    const box = el.getBoundingClientRect();
    const tabs = [...el.querySelectorAll('a')].map((a) => a.getBoundingClientRect());
    const on = el.querySelector('[aria-current="page"]')!.getBoundingClientRect();
    return {
      tops: [...new Set(tabs.map((t) => Math.round(t.top)))].length,
      scrolls: el.scrollWidth > el.clientWidth,
      onInView: on.left >= box.left - 1 && on.right <= box.right + 1,
      fades: [el.classList.contains('more-start'), el.classList.contains('more-end')],
    };
  });
}

test("the Plan's five tabs are one row that scrolls, with the far edge faded", async ({ page }) => {
  await page.goto('/b/ours/plan');
  const r = await row(page, 'Plan pages');
  expect(r.tops).toBe(1);
  expect(r.scrolls).toBe(true);
  expect(r.onInView).toBe(true);
  await expect(page.getByRole('navigation', { name: 'Plan pages' })).toHaveClass(/\bmore-end\b/);
});

test("Spending's last tab, when it is the current one, is scrolled into view, and the near edge fades instead", async ({ page }) => {
  await page.goto('/b/ours/spending/reimbursements');
  const nav = page.getByRole('navigation', { name: 'Spending views' });
  await expect(nav).toHaveClass(/\bmore-start\b/);
  const r = await row(page, 'Spending views');
  expect(r.tops).toBe(1);
  expect(r.onInView).toBe(true);
  expect(r.fades).toEqual([true, false]);
});
