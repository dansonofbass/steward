import { expect, test } from '@playwright/test';
import { DEMO, restoreVault } from './fixtures';
import { loaded, open, origin, signIn } from './open-screen';
import { DEMO_PORT } from './ports';
import { addDemoRecords, SCREENS } from './screens';

// Moving by headings (issue #21): every screen in screens.ts has exactly one level 1 heading, and no heading skips a
// level below the one before it (h1 then h3). axe's WCAG tags don't check either, so axe.spec.ts can't catch it.
// Both projects: a phone layout can show or hide headings a laptop doesn't.

test.beforeAll(async ({ playwright }) => {
  await restoreVault();
  const request = await playwright.request.newContext({ baseURL: `http://localhost:${DEMO_PORT}` });
  expect((await request.post('/api/auth/login', { data: { username: 'alex', password: DEMO.alex, device_label: 'e2e' } })).ok()).toBeTruthy();
  await addDemoRecords(request);
  await request.dispose();
});

for (const s of SCREENS) {
  test(`${s.name} has one level 1 heading and skips no level`, async ({ page }, info) => {
    const at = origin(s, info.project.name);
    if (s.signedIn) await signIn(page, at);
    await page.goto(`${at}/api/health`);
    await open(page, `${at}${s.url}`, 'light', 'day');
    await loaded(page, s);
    // The headings a screen reader lists: rendered (a visually hidden one counts), not hidden from it, in page order.
    // The level: aria-level, else the tag's number, else 2 (a role="heading" with no aria-level).
    const headings = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>('h1, h2, h3, h4, h5, h6, [role="heading"]')]
      .filter((h) => h.checkVisibility({ visibilityProperty: true }) && !h.closest('[aria-hidden="true"], [inert]'))
      .map((h) => {
        const aria = Number.parseInt(h.getAttribute('aria-level') ?? '', 10);
        const tag = /^H([1-6])$/.exec(h.tagName)?.[1];
        const level = aria > 0 ? aria : tag ? Number(tag) : 2;
        return { level, text: (h.textContent ?? '').replace(/\s+/g, ' ').trim() };
      }));
    const outline = headings.map((h) => `h${h.level} ${h.text}`);
    expect(headings.filter((h) => h.level === 1).length, `one h1:\n${outline.join('\n')}`).toBe(1);
    const skips = headings.flatMap((h, i) => (i > 0 && h.level > headings[i - 1].level + 1 ? [`${outline[i - 1]} -> ${outline[i]}`] : []));
    expect(skips, `no skipped level:\n${outline.join('\n')}`).toEqual([]);
    expect(headings[0]?.level, `the first heading is the h1:\n${outline.join('\n')}`).toBe(1);
  });
}
