// Issue #22: three layout problems at phone width. jsdom lays nothing out, so these pin the rules that fix them; the
// tab row's one line is also checked in a phone browser (e2e/phone-layout.spec.ts).
import { describe, expect, it } from 'vitest';
import { readCss, rule } from '../test-css';

describe('phone layout (#22)', () => {
  it("a business rule wraps inside its own words, and the Remove button's label stays whole", () => {
    const css = readCss('screens/business/business.css');
    expect(rule(css, '.biz-rule')).not.toContain('overflow-wrap');
    expect(rule(css, '.biz-rule > span')).toBe('min-width: 0; overflow-wrap: anywhere;');
    expect(rule(css, '.biz-rule > .btn')).toBe('flex: none;');
  });

  it("the toast's dot and Undo wrap together, so the dot never hangs at the end of the line above", () => {
    expect(rule(readCss('ui/UndoToast.css'), '.undo-toast__undo')).toBe('flex: none; display: inline-flex; align-items: center; gap: var(--s-1);');
  });
});
