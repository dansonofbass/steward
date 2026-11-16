// Phase 17 (spec 2.3): no white flashes at night. The Undo toast, the "Ten in a row" pop and the tip bubble are raised
// chips in the dark phases (surface-2, ink, a 1px line ring), not inverted near-white slabs; the sheet's backdrop is
// deeper, and raised layers get a 1px top highlight. Light phases keep the ink slab.
import { describe, expect, it } from 'vitest';
import { darkRule, readCss, rule } from '../test-css';

describe('no white flashes at night (phase 17, 2.3)', () => {
  it('the toast, the pop and the tip are raised chips in the dark phases and the ink slab in light', () => {
    for (const [file, sel] of [['ui/UndoToast.css', '.undo-toast'], ['celebrate/celebrate.css', '.cel-pop'], ['ui/Tip.css', '.tip__body']] as const) {
      const css = readCss(file);
      expect(rule(css, sel), file).toMatch(/background: var\(--ink\); color: var\(--bg\)/);
      const dark = darkRule(css, sel);
      expect(dark, file).toContain('background: var(--surface-2)');
      expect(dark, file).toContain('color: var(--ink)');
      expect(dark, file).toContain('box-shadow: 0 0 0 1px var(--line), var(--shadow-raised)');
    }
  });

  it("Undo's word, and the Settle link, take the plum text colour on the dark toast", () => {
    expect(darkRule(readCss('ui/UndoToast.css'), '.undo-toast .link')).toBe('color: var(--accent-text);');
  });

  it('the sheet backdrop is deeper in the dark phases, and raised layers get a 1px top highlight', () => {
    const sheet = readCss('ui/Sheet.css');
    expect(rule(sheet, '.sheet::backdrop')).toContain('background: rgb(0 0 0 / 0.45)');
    expect(darkRule(sheet, '.sheet::backdrop')).toBe('background: rgb(0 0 0 / 0.65);');
    expect(darkRule(sheet, '.sheet:modal')).toBe('box-shadow: var(--shadow-raised);');
    const tokens = readCss('styles/tokens.css');
    expect(rule(tokens, ':root[data-phase="night"]'))
      .toContain('--shadow-raised: inset 0 1px 0 rgba(255, 255, 255, 0.08), 0 20px 40px -24px rgba(0, 0, 0, 0.7);');
    expect(rule(tokens, ':root')).toContain('--shadow-raised: 0 20px 40px -24px rgba(0, 0, 0, 0.35);');   // light: as today
  });
});
