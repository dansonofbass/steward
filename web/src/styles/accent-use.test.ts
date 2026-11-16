// Phase 17 (spec 2.1): --accent is a fill (buttons, ticks on, the selected segment) with --accent-ink on it. Anything that
// reads as text or a line (links, the current tab, rings, chart lines, a selected row's edge) is --accent-text, the same
// plum in the light phases and a light plum in the dark ones. This fails on a declaration that draws with --accent any
// other way; the list says where.
import { describe, expect, it } from 'vitest';
import { allCss } from '../test-css';

const FILL = /^(background|background-color|accent-color)$/;
// The palette itself, and the mark (its tile is var(--mark-tile, var(--accent)): the dark phases set --mark-tile).
const SKIP = new Set(['styles/sky.css', 'ui/Mark.css']);
const outsideMix = (v: string) => v.replace(/color-mix\([^()]*(\([^()]*\)[^()]*)*\)/g, '');

describe('--accent is only ever a fill (phase 17)', () => {
  it('every other use of the plum is --accent-text (or --focus for a ring)', () => {
    const wrong: string[] = [];
    for (const [file, css] of allCss()) {
      if (SKIP.has(file)) continue;
      for (const m of css.matchAll(/([\w-]+)\s*:\s*([^;{}]*var\(--accent\)[^;{}]*)/g)) {
        const [, prop, value] = m;
        if (FILL.test(prop) || !outsideMix(value).includes('var(--accent)')) continue;
        wrong.push(`${file}: ${prop}: ${value.trim()}`);
      }
    }
    expect(wrong).toEqual([]);
  });
});
