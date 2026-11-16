import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { DEMO, restoreVault } from './fixtures';
import { loaded, open, origin, signIn, THEMES } from './open-screen';
import { DEMO_PORT } from './ports';
import { addDemoRecords, SCREENS } from './screens';

// T7 (docs/CLAIMS.md): axe finds nothing on any screen, on a phone and a laptop (both projects), dark and light.
// Every screen in screens.ts; src/routes.screens.test.ts keeps that list in step with routes.tsx. There is no rule
// exception list.

const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

test.beforeAll(async ({ playwright }) => {
  await restoreVault();
  // The set-aside and trip pages need one of each, which the demo seeds don't have.
  const request = await playwright.request.newContext({ baseURL: `http://localhost:${DEMO_PORT}` });
  expect((await request.post('/api/auth/login', { data: { username: 'alex', password: DEMO.alex, device_label: 'e2e' } })).ok()).toBeTruthy();
  await addDemoRecords(request);
  await request.dispose();
});

for (const s of SCREENS) {
  test(`${s.name} has no axe violations, dark and light`, async ({ page }, info) => {
    const at = origin(s, info.project.name);
    if (s.signedIn) await signIn(page, at);
    await page.goto(`${at}/api/health`);   // an origin to write the theme setting on
    const found: { theme: string; id: string; impact: string | null | undefined; nodes: string[] }[] = [];
    for (const [theme, phase] of THEMES) {
      await open(page, `${at}${s.url}`, theme, phase);
      await loaded(page, s);
      const { violations } = await new AxeBuilder({ page }).withTags(TAGS).analyze();
      found.push(...violations.map((v) => ({ theme, id: v.id, impact: v.impact, nodes: v.nodes.map((n) => n.target.join(' ')) })));
    }
    expect(found).toEqual([]);
  });
}
