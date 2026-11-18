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

  // #22 replaced the wrap: a five-tab row wrapped its fifth tab onto a line by itself. The row stays one line and
  // scrolls, and an edge with more beyond it fades, so a tab the edge cuts reads as more to scroll to ("Next dolla…").
  it('a phone tab row stays one line and scrolls, faded at an edge with more tabs beyond it (#22)', () => {
    const css = readCss('ui/SubNav.css');
    expect(rules(css).some((r) => r.sel.includes('.subnav') && r.body.includes('flex-wrap'))).toBe(false);
    expect(rule(css, '.subnav')).toContain('overflow-x: auto;');
    expect(rule(css, '.subnav')).toContain('mask-image: linear-gradient(to right, transparent, #000 var(--subnav-fade-start), #000 calc(100% - var(--subnav-fade-end)), transparent);');
    expect(rule(css, '.subnav.more-start')).toBe('--subnav-fade-start: var(--subnav-fade);');
    expect(rule(css, '.subnav.more-end')).toBe('--subnav-fade-end: var(--subnav-fade);');
  });

  it("Appearance's switches sit beside their words, not across the card", () => {
    expect(rule(readCss('screens/Settings.css'), '.line.check-row')).toBe('display: flex; justify-content: flex-start;');
  });
});
