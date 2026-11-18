import { expect, test } from '@playwright/test';
import { DEMO, restoreVault } from './fixtures';
import { loaded, open, origin, signIn } from './open-screen';
import { DEMO_PORT } from './ports';
import { addDemoRecords, SCREENS } from './screens';

// Issue #28: with the phone's text at 200%, every screen still fits the phone's width: nothing runs off the side and
// the page never scrolls sideways. Type is in rem and index.html opts in to the text size, so doubling the browser's
// default font size is what a phone set to 200% does to the page. Phone project only.

test.beforeAll(async ({ playwright }) => {
  await restoreVault();
  const request = await playwright.request.newContext({ baseURL: `http://localhost:${DEMO_PORT}` });
  expect((await request.post('/api/auth/login', { data: { username: 'alex', password: DEMO.alex, device_label: 'e2e' } })).ok()).toBeTruthy();
  await addDemoRecords(request);
  await request.dispose();
});

for (const s of SCREENS) {
  test(`${s.name} fits a phone with its text at 200%`, async ({ page }, info) => {
    test.skip(info.project.name !== 'phone', 'the phone layouts');
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Page.enable');
    await cdp.send('Page.setFontSizes', { fontSizes: { standard: 32 } });
    const at = origin(s, info.project.name);
    if (s.signedIn) await signIn(page, at);
    await page.goto(`${at}/api/health`);   // an origin to write the theme setting on
    await open(page, `${at}${s.url}`, 'light', 'day');
    await loaded(page, s);
    const fit = await page.evaluate(() => {
      const vw = document.documentElement.clientWidth;
      const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
      // What sticks out past the right edge, for the message: the outermost such element of each run. A wide table
      // inside its own sideways scroller is fine; content cut off by a box that hides its overflow is not.
      const scroller = (e: Element) => {
        for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) if (/auto|scroll/.test(getComputedStyle(p).overflowX)) return true;
        return false;
      };
      const out = [...document.querySelectorAll('body *')].filter((e) => {
        const r = e.getBoundingClientRect();
        if (r.width === 0 || r.right <= vw + 1 || scroller(e)) return false;
        const p = e.parentElement?.getBoundingClientRect();
        return !p || p.right <= vw + 1;
      }).slice(0, 5).map((e) => `${e.tagName.toLowerCase()}.${String((e as HTMLElement).className).split(' ')[0]} right ${Math.round(e.getBoundingClientRect().right)}`);
      return { rem, scroll: document.documentElement.scrollWidth, vw, out };
    });
    expect(fit.rem, 'the root font size follows the text size').toBe(32);
    expect({ scroll: fit.scroll, out: fit.out }, `${s.name}: page width ${fit.vw}`).toEqual({ scroll: fit.vw, out: [] });
  });
}
