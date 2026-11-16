// Exactly one initials button shows at each width: the phone's top bar below 900 px, the rail's foot from 900 px.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';

// Read as text: the test runner's CSS plugin returns an empty string for imported stylesheets (see Nav.css.test.ts).
const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8');
const topBarCss = read('./TopBar.css');
const navCss = read('../ui/Nav.css');

describe('One You button at each width', () => {
  it('the top bar is hidden from 900 px', () => {
    expect(topBarCss).toMatch(/@media \(min-width: 900px\) \{\s*\.topbar \{\s*display: none;\s*\}\s*\}/);
  });
  it('the rail foot is hidden below 900 px and shown from 900 px', () => {
    expect(navCss).toMatch(/^\.nav__foot \{\s*display: none;\s*\}/m);
    const wide = navCss.match(/@media \(min-width: 900px\) \{\s*\.nav--auto \.nav__foot, \.nav--rail \.nav__foot \{([^}]*)\}/)?.[1] ?? '';
    expect(wide).toMatch(/display: block/);
  });
});
