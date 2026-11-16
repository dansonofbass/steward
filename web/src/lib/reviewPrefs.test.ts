import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearDemo, demoState, readView, saveView, setDemo, setSwipe, swipeOn } from './reviewPrefs';

afterEach(() => { vi.restoreAllMocks(); });

describe('review prefs (review focus, Data)', () => {
  it('keeps the view per person on this device, focus by default', () => {
    expect(readView(1)).toBe('focus');
    saveView(1, 'list');
    expect(readView(1)).toBe('list');
    expect(readView(2)).toBe('focus');
    expect(localStorage.getItem('steward-review-view:1')).toBe('list');
    expect(readView(null)).toBe('focus');
  });

  it('Swipe to sort is on until switched off, and the demo goes nudged then done, never back', () => {
    expect(swipeOn()).toBe(true);
    setSwipe(false);
    expect(localStorage.getItem('steward-swipe')).toBe('off');
    expect(swipeOn()).toBe(false);
    setSwipe(true);
    expect(localStorage.getItem('steward-swipe')).toBeNull();
    expect(demoState()).toBeNull();
    setDemo('nudged');
    expect(demoState()).toBe('nudged');
    setDemo('done');
    setDemo('nudged');
    expect(demoState()).toBe('done');
    clearDemo();
    expect(demoState()).toBeNull();
  });

  it('with storage throwing: focus, swipes on, and the nudge once per page load', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('private'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('private'); });
    saveView(1, 'list');
    expect(readView(1)).toBe('focus');
    expect(swipeOn()).toBe(true);
    expect(demoState()).toBeNull();
    setDemo('nudged');
    expect(demoState()).toBe('nudged');
  });
});
