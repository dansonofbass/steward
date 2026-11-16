// WEB-11 (release gate 0.1.0, fix 16i): in forced colours (Windows High Contrast) backgrounds and box-shadows are
// replaced, so a state they alone showed vanishes. base.css gives every selection state a system-colour outline and
// every focus ring one that outline: none can't remove. A scan of every stylesheet fails on a selection state that
// isn't in that list.
import { describe, expect, it } from 'vitest';
import { allCss, readCss, uncomment } from '../test-css';

/** The forced-colours block of base.css, as text. */
function forcedBlock(css: string): string {
  const at = css.indexOf('@media (forced-colors: active)');
  expect(at).toBeGreaterThanOrEqual(0);
  let depth = 0;
  for (let i = css.indexOf('{', at); i < css.length; i++) {
    if (css[i] === '{') depth++;
    else if (css[i] === '}' && --depth === 0) return css.slice(at, i + 1);
  }
  return css.slice(at);
}

/** The selection states a stylesheet styles: an is-* class named for being chosen, or an ARIA state set to true. */
const STATE = /\.is-(?:on|picked|selected|active|current|chosen|checked)\b|\[aria-(?:pressed|checked|selected)="true"\]|\[aria-current="page"\]/g;

describe('forced colours keep states and focus visible (WEB-11)', () => {
  const block = forcedBlock(uncomment(readCss('styles/base.css')));

  it('every selection state any stylesheet styles has a forced-colours outline', () => {
    const used = new Set<string>();
    for (const [, css] of allCss()) for (const m of css.matchAll(STATE)) used.add(m[0]);
    expect(used.size).toBeGreaterThanOrEqual(8);                 // floor: the scan still finds what it checks
    expect([...used].filter((s) => !block.includes(s))).toEqual([]);
    expect(block).toMatch(/outline: 2px solid Highlight; outline-offset: -2px;/);
  });

  it('a chosen state focused still reads as chosen: a second sign besides the outline the focus ring replaces (16i review Minor 6)', () => {
    const states = /\.is-on, [^{]*\{([^}]*)\}/.exec(block)?.[1] ?? '';
    expect(states).toMatch(/text-decoration: underline 2px/);
  });

  it('a focus ring stays in forced colours, whatever a rule set outline to', () => {
    expect(block).toMatch(/:focus-visible \{ outline: 2px solid Highlight !important;/);
    const hidden = allCss().filter(([, css]) => /:focus-visible[^{]*\{[^}]*outline: none/.test(css)).map(([f]) => f);
    expect(hidden.length).toBeGreaterThan(0);                   // the case it covers still exists (fmenu, sign links)
  });
});
