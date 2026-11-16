// WEB-17 (release gate 0.1.0, fix 16i): Enter that confirms an input method's conversion never saves. The helper, one
// real handler (the category search), and a scan: every handler that acts on Enter checks composing(), or is listed.
import { fireEvent, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { stubFetch, wrap } from '../test-utils';
import { CategoryField } from '../ui/CategoryMenu';
import { composing } from './ime';

const SOURCES: Record<string, string> = Object.fromEntries(
  Object.entries(import.meta.glob<string>('/src/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }))
    .filter(([path]) => !/\.test\.[jt]sx?$/.test(path)),
);

/** Enter handlers on things you don't type into, or that need a modifier, with why. */
const NOT_TYPING: Record<string, string> = {
  '/src/screens/transactions/Filters.tsx': 'a listbox option: Enter chooses it, and no text is being composed',
  '/src/screens/review/keys.ts': "Review's card keys, which skip text fields",
  '/src/screens/review/focus/keymap.ts': "focus mode's card keys, which skip text fields",
  '/src/screens/chat/Composer.tsx': 'Ctrl or Cmd+Enter sends; an input method never confirms with a modifier',
};

describe('composing (WEB-17)', () => {
  it('is true while composing, and for Safari\'s keyCode 229 after the composition ended', () => {
    expect(composing(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true }))).toBe(true);
    expect(composing(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 229 }))).toBe(true);
    expect(composing(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13 }))).toBe(false);
  });

  describe('the category search on a phone', () => {
    beforeEach(() => {
      stubFetch({ '/api/categorize/usual': { keys: [] } });
      vi.stubGlobal('matchMedia', (q: string) => ({ matches: false, media: q, addEventListener: () => {}, removeEventListener: () => {} }));
    });
    afterEach(() => vi.unstubAllGlobals());
    function Harness() {
      const [v, setV] = useState('groceries');
      return <><CategoryField value={v} onChange={setV} /><output data-testid="picked">{v}</output></>;
    }

    it('an Enter that confirms a conversion picks nothing; a plain Enter picks', () => {
      wrap(<Harness />);
      fireEvent.click(screen.getByRole('button', { name: /^Category / }));
      const box = screen.getByRole('combobox', { name: 'Find a category' });
      fireEvent.change(box, { target: { value: 'pet' } });
      fireEvent.keyDown(box, { key: 'Enter', isComposing: true });
      fireEvent.keyDown(box, { key: 'Enter', keyCode: 229 });
      expect(screen.getByTestId('picked')).toHaveTextContent('groceries');
      fireEvent.keyDown(box, { key: 'Enter', keyCode: 13 });
      expect(screen.getByTestId('picked')).toHaveTextContent('pets');
    });
  });

  it('every handler that acts on Enter checks composing(), unless listed', () => {
    const acting = Object.entries(SOURCES).filter(([, src]) => /key === 'Enter'/.test(src));
    expect(acting.length).toBeGreaterThanOrEqual(8);
    const missing = acting.filter(([path, src]) => !(path in NOT_TYPING) && !/\bcomposing\(e\)/.test(src)).map(([p]) => p);
    expect(missing).toEqual([]);
    for (const path of Object.keys(NOT_TYPING)) expect(SOURCES[path], path).toMatch(/key === 'Enter'/);
  });
});
