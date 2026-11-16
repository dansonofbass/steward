// Phase 17 (spec 2.7): the audit's small fixes. Each is a deliberate change in light too.
import { describe, expect, it } from 'vitest';
import { readCss, rule, rules } from '../test-css';

describe('small fixes (phase 17, 2.7)', () => {
  it("the Care legend's markers stay marker-sized: only the chart's own svg fills the width", () => {
    const care = readCss('screens/care/care.css');
    expect(rule(care, '.care-chart > svg')).toContain('width: 100%');
    expect(rule(care, '.care-chart svg')).toBe('');
    expect(rule(care, '.care-legend svg')).toBe('flex: none;');
  });

  it('a phone tab row wraps onto a second line instead of cutting a label ("Next dolla…")', () => {
    const phone = rules(readCss('ui/SubNav.css')).find((r) => r.sel.includes('.subnav') && r.body.includes('flex-wrap'));
    expect(phone?.body).toBe('flex-wrap: wrap; column-gap: var(--s-4); row-gap: 0; overflow-x: visible;');
    expect(readCss('ui/SubNav.css')).toMatch(/@media \(max-width: 899px\) \{\s*\.subnav \{ flex-wrap: wrap;/);
  });

  it("Appearance's switches sit beside their words, not across the card", () => {
    expect(rule(readCss('screens/Settings.css'), '.line.check-row')).toBe('display: flex; justify-content: flex-start;');
  });
});
