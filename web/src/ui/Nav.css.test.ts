// The phone tab bar's CSS (parent care final review M3): a household book's six tabs fit a 320 px phone on one line.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { navItems } from './Nav';
import { DARK, darkRule, rule } from '../test-css';

// Read as text: the test runner's CSS plugin returns an empty string for imported stylesheets. The path goes through
// a function so the bundler doesn't turn the URL into an asset link.
const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8');
const navCss = read('./Nav.css');

describe('Six tabs on a 320 px phone', () => {
  it('fit on one line, so the page never scrolls sideways', () => {
    const phone = navCss.match(/@media \(max-width: 899px\) \{\s*\.nav__link \{([^}]*)\}/)?.[1] ?? '';
    expect(phone).toMatch(/font-size: 12px/);
    expect(phone).toMatch(/white-space: nowrap/);
    const side = Number(phone.match(/padding: var\(--s-2\) (\d+)px/)?.[1]);
    expect(side).toBe(2);
    // Measured in Chromium at 320 px: the six labels in Source Sans 3 at 12 px take 248 px, about 5.8 px a letter.
    // Counting 0.55 em (6.6 px) a letter leaves room for the current tab's bolder weight and a longer label.
    const labels = navItems('ours', 'household').map((i) => i.label);
    expect(labels).toHaveLength(6);
    const width = labels.reduce((w, label) => w + label.length * 12 * 0.55 + 2 * side, 0);
    expect(width).toBeLessThanOrEqual(320);
    expect(navCss).toContain('Six tabs on the phone');
  });

  it('keeps the last tab\'s count inside the bar', () => {
    const phone = navCss.match(/@media \(max-width: 899px\) \{([^@]*)\}\s*\n/)?.[1] ?? '';
    expect(phone).toMatch(/\.nav--auto \.nav__item:last-child \.nav__count \{\s*left: auto;\s*right: 4px;/);
  });
});

describe('The brand at the top of the rail', () => {
  it('shows in the rail only: hidden by default, shown for the rail and for the auto layout from 900 px', () => {
    expect(navCss).toMatch(/\n\.nav__brand \{ display: none; \}/);
    expect(navCss).toMatch(/\n\.nav--rail \.nav__brand \{ display: flex; \}/);
    expect(navCss).toMatch(/@media \(min-width: 900px\) \{\s*\.nav--auto \.nav__brand \{ display: flex; \}/);
  });
  it('sets the word in the display serif at 20 px, weight 600', () => {
    expect(navCss).toMatch(/\.nav__brand-name \{ font: 600 20px\/1 var\(--font-display\);/);
  });
});

describe('The current tab (phase 17, spec 2.1)', () => {
  it('is the plum in light, and ink on its pill in the dark phases, on the rail and the phone bar', () => {
    expect(rule(navCss, '.nav__link.active')).toContain('color: var(--accent-text)');
    expect(darkRule(navCss, '.nav__link.active')).toContain('color: var(--ink)');
    const pill = darkRule(navCss, ':is(.nav--bar, .nav--auto) .nav__link.active::before');
    expect(pill).toContain('background: var(--surface-2)');
    expect(pill).toContain('z-index: -1');
    expect(darkRule(navCss, ':is(.nav--bar, .nav--auto) .nav__link.active')).toContain('isolation: isolate');
    expect(navCss).toContain(DARK);
  });
});
