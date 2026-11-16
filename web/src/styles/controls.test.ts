// Phase 17 (spec 2.2; rulings R1, R3, R4): controls that follow the theme. Steward draws every tick and radio, in every
// phase (the UA's turn muddy grey at night); every form field's edge reads at 3:1 (--line-strong); the selected segment
// is the plum fill in the dark phases, lighter than its track; the chosen Inventory pill is the plum fill everywhere;
// and a fieldset card has no browser border.
import { describe, expect, it } from 'vitest';
import { allCss, darkRule, readCss, rule, rules } from '../test-css';

const base = readCss('styles/base.css');
const BOXES = ':is(input[type="checkbox"]:not(.pick-box), input[type="radio"])';
const isDrawn = (s: string) => s.includes('input[type="checkbox"]:not(.pick-box)') || s.includes('input[type="radio"]:not(.pick-box)');

describe('ticks and radios (phase 17, 2.2, ruling R1)', () => {
  it('Steward draws them: a muted ring, then the plum fill with a white mark when on', () => {
    const box = rule(base, BOXES);
    expect(box).toContain('appearance: none');
    expect(box).toContain('width: 20px; height: 20px');
    expect(box).toContain('box-shadow: inset 0 0 0 2px var(--ink-muted)');
    expect(rule(base, 'input[type="radio"]:not(.pick-box)')).toBe('border-radius: 50%;');
    expect(rule(base, 'input[type="checkbox"]:not(.pick-box):checked'))
      .toMatch(/background: var\(--accent\) url\("data:image\/svg\+xml,[^"]*stroke='%23FFFFFF'/);
    expect(rule(base, 'input[type="radio"]:not(.pick-box):checked')).toContain('radial-gradient(circle, var(--accent-ink) 0 4px, var(--accent) 4.5px)');
  });

  it('in every phase, light included: no drawn rule names a phase, and the native rule is gone', () => {
    const drawn = rules(base).filter((r) => r.sel.some(isDrawn));
    for (const r of drawn) expect(r.sel.join(', ')).not.toMatch(/data-phase|theme-dark/);
    expect(rule(base, 'input[type="checkbox"]')).toBe('');
  });

  it('never moves or shows an input a screen hides (Inventory\'s pill choices): no position, display or opacity', () => {
    const drawn = rules(base).filter((r) => r.sel.some(isDrawn));
    expect(drawn.length).toBeGreaterThanOrEqual(6);
    for (const r of drawn) expect(r.body, r.sel.join(', ')).not.toMatch(/(^|; )(position|display|opacity):/);
    expect(rule(readCss('screens/inventory/inventory.css'), '.inv-seg input')).toContain('opacity: 0');
  });

  it('in forced colours (Windows high contrast) the drawn boxes go back to the native ones', () => {
    const both = rules(base).filter((r) => r.sel.includes(BOXES));
    expect(both).toHaveLength(2);
    expect(both[1].body).toBe('appearance: auto;');
    expect(base).toMatch(/@media \(forced-colors: active\) \{\s*:is\(input\[type="checkbox"\]/);
  });
});

describe('form fields (ruling R3)', () => {
  it("every text input's, select's and textarea's edge is --line-strong; --line stays for decoration", () => {
    const FIELD = /(^|[\s>+~(,])(input|select|textarea)\b(?![-\w])/;
    const wrong: string[] = [];
    for (const [file, css] of allCss()) {
      for (const r of rules(css)) {
        if (!r.sel.some((s) => FIELD.test(s)) || r.sel.every((s) => /type="(checkbox|radio)"/.test(s))) continue;
        if (/(^|; )(border|border-color|box-shadow)[^;]*var\(--line\)/.test(r.body)) wrong.push(`${file}: ${r.sel.join(', ')}`);
      }
    }
    expect(wrong).toEqual([]);
    expect(rule(base, 'textarea')).toContain('border: 1px solid var(--line-strong)');   // preflight F1: the shared field rule
    expect(rule(readCss('ui/Field.css'), '.field select')).toContain('border: 1px solid var(--line-strong)');
    expect(rule(readCss('screens/Settings.css'), '.field textarea')).toContain('border: 1px solid var(--line-strong)');
    expect(rule(readCss('screens/chat/ask.css'), '.composer textarea')).toContain('border: 1px solid var(--line-strong)');
  });
});

describe('segmented controls and the fieldset card (phase 17, 2.2)', () => {
  it('the selected segment is the plum fill on a page-coloured track in the dark phases, never pressed in', () => {
    for (const [file, track, on] of [
      ['screens/spending/spending.css', '.sp-span', '.sp-span button.is-on'],
      ['screens/transactions.css', '.seg', '.seg button.is-on'],
    ] as const) {
      const css = readCss(file);
      expect(darkRule(css, track), file).toContain('background: var(--bg); box-shadow: inset 0 0 0 1px var(--line)');
      expect(darkRule(css, on), file).toContain('background: var(--accent); color: var(--accent-ink); box-shadow: none');
      expect(rule(css, on), file).toContain('background: var(--surface); color: var(--ink)');   // light: as today
    }
    expect(darkRule(readCss('screens/review.css'), '.rtop__view button[aria-pressed="true"]')).toContain('background: var(--accent); color: var(--accent-ink)');
  });

  it('the chosen Inventory pill is the plum fill with white text in every phase (ruling R4; it was white on light grey)', () => {
    const inv = readCss('screens/inventory/inventory.css');
    expect(rule(inv, '.inv-seg label.is-on')).toBe('border-color: transparent; color: var(--accent-ink); background: var(--accent);');
    expect(darkRule(inv, '.inv-seg label.is-on')).toBe('');   // one rule for every phase
    // white on --accent at 4.5:1 in every phase is pinned by sky.contrast.test.ts
  });

  it('a fieldset card draws no browser border (the double ring on Appearance)', () => {
    expect(rule(readCss('ui/Card.css'), 'fieldset.card')).toBe('border: 0;');
  });
});
