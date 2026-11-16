import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { resetTourLoad } from '../../lib/askTour';
import { resetTourHidden, useAskTour } from './useAskTour';

beforeEach(() => { localStorage.clear(); resetTourLoad(); resetTourHidden(); });

describe('useAskTour (P23)', () => {
  it('shows while What Claude will see is on screen, until the person finishes it', () => {
    const { result, rerender } = renderHook(({ v }) => useAskTour(1, v), { initialProps: { v: false } });
    expect(result.current.show).toBe(false);
    rerender({ v: true });
    expect(result.current.show).toBe(true);
    act(() => { result.current.done(); });
    expect(result.current.show).toBe(false);
    expect(localStorage.getItem('steward-ask-tour:1')).toBe('done');
  });
  it('waits for the person: with no user yet there is no tip', () => {
    expect(renderHook(() => useAskTour(null, true)).result.current.show).toBe(false);
  });
  it('replays from the label without touching storage; hiding it ends it for this page', () => {
    localStorage.setItem('steward-ask-tour:1', 'done');
    const { result } = renderHook(() => useAskTour(1, true));
    expect(result.current.show).toBe(false);
    act(() => { result.current.toggle(); });
    expect(result.current.show).toBe(true);
    act(() => { result.current.hide(); });
    expect(result.current.show).toBe(false);
    expect(localStorage.getItem('steward-ask-tour:1')).toBe('done');
  });
  it('in the Ask tab, Escape closes it without marking it done', () => {
    const { result } = renderHook(() => useAskTour(2, true, true));
    expect(result.current.show).toBe(true);
    act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); });
    expect(result.current.show).toBe(false);
    expect(localStorage.getItem('steward-ask-tour:2')).toBeNull();
  });
});
