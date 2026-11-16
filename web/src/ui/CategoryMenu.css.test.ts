// The desktop category menu never scrolls sideways (JR, Oct 28). Its list was CSS columns in a box of fixed height:
// columns that run out of height add more columns to the side, so the list grew to about 2,900 px wide inside a
// 300 px menu, and the arrow keys scrolled it sideways past your usual. jsdom does no layout, so this pins the rules
// that keep it two columns of rows that only scroll down; e2e/catmenu.spec.ts measures the real thing.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { MENU_W } from '../lib/menuPlace';

// Read as text: the test runner's CSS plugin returns an empty string for imported stylesheets. The path goes through
// a function so the bundler doesn't turn the URL into an asset link.
const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8');
const css = read('./CategoryMenu.css').replace(/\/\*[\s\S]*?\*\//g, '');
const rule = (selector: string) => {
  const at = css.indexOf(`${selector} {`);
  expect(at, selector).toBeGreaterThanOrEqual(0);
  return css.slice(at, css.indexOf('}', at));
};

describe('CategoryMenu.css (the desktop menu: two columns of rows, no sideways scroll)', () => {
  it('uses no CSS columns, which overflow sideways in a list of fixed height', () => {
    expect(css).not.toMatch(/column-count|(^|[\s;{])columns\s*:|column-span|column-width/);
  });

  it('scrolls the list down, never sideways', () => {
    const list = rule('.catmenu__list');
    expect(list).toMatch(/overflow-x: hidden/);
    expect(list).toMatch(/overflow-y: auto/);
    expect(list).toMatch(/min-height: 0/);
  });

  it('lays each group out as two equal columns that can shrink, the heading across both', () => {
    expect(rule('.catmenu-pop .catmenu__list--grouped .catmenu__group')).toMatch(/display: grid; grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/);
    expect(rule('.catmenu-pop .catmenu__list--grouped .catmenu__head')).toMatch(/grid-column: 1 \/ -1/);
  });

  it('wraps a long label inside its column', () => {
    const opt = rule('.catmenu__opt');
    expect(opt).toMatch(/min-width: 0/);
    expect(opt).toMatch(/overflow-wrap: anywhere/);
  });

  it('keeps the two-column grid to the desktop popover: the phone sheet is one column', () => {
    for (const m of css.matchAll(/([^{}]*)\{[^}]*display: grid/g)) expect(m[1].trim()).toMatch(/^\.catmenu-pop /);
  });

  it('is about 300 px wide, room for two columns of rows', () => {
    expect(MENU_W).toBeGreaterThanOrEqual(300);
    expect(MENU_W).toBeLessThanOrEqual(340);
  });
});
