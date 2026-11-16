import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useFakeTimers } from '../../test-clock';
import { callsTo, reply, stubFetch } from '../../test-utils';
import { useHomeVisit } from './useHomeVisit';

const MARK = '2026-10-30T19:00:00+00:00';
const LATER_MARK = '2026-10-30T19:00:05+00:00';
let visibility: DocumentVisibilityState = 'visible';
const show = (s: DocumentVisibilityState) => { visibility = s; document.dispatchEvent(new Event('visibilitychange')); };
const looks = (fetchMock: ReturnType<typeof stubFetch>) => callsTo(fetchMock, 'POST', '/api/home/seen').map((c) => c.body);

beforeEach(() => {
  visibility = 'visible';
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visibility });
  useFakeTimers();
});
afterEach(() => { Reflect.deleteProperty(document, 'visibilityState'); vi.useRealTimers(); vi.unstubAllGlobals(); });
const NO_CONTENT = () => new Response(null, { status: 204 });

describe('useHomeVisit (Home spec P27, P28)', () => {
  it('sends nothing before the mark, one glance once it comes, and one full look at 10 s, not 9.999', () => {
    const fetchMock = stubFetch({ 'POST /api/home/seen': NO_CONTENT });
    const { rerender } = renderHook(({ mark }: { mark?: string }) => useHomeVisit(mark), { initialProps: {} });
    expect(looks(fetchMock)).toEqual([]);
    rerender({ mark: MARK });
    expect(looks(fetchMock)).toEqual([{ mark: MARK, glance: true }]);
    act(() => { vi.advanceTimersByTime(9_999); });
    expect(looks(fetchMock)).toHaveLength(1);
    act(() => { vi.advanceTimersByTime(1); });
    expect(looks(fetchMock)).toEqual([{ mark: MARK, glance: true }, { mark: MARK, glance: false }]);
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(looks(fetchMock)).toHaveLength(2);                                  // once per mount
  });

  it('counts visible time only', () => {
    const fetchMock = stubFetch({ 'POST /api/home/seen': NO_CONTENT });
    renderHook(() => useHomeVisit(MARK));
    act(() => { vi.advanceTimersByTime(4_000); });
    act(() => { show('hidden'); });
    act(() => { vi.advanceTimersByTime(20_000); });
    act(() => { show('visible'); });
    act(() => { vi.advanceTimersByTime(5_999); });
    expect(looks(fetchMock)).toHaveLength(1);
    act(() => { vi.advanceTimersByTime(1); });
    expect(looks(fetchMock)[1]).toEqual({ mark: MARK, glance: false });
  });

  it('a mount that starts hidden waits until it is shown', () => {
    visibility = 'hidden';
    const fetchMock = stubFetch({ 'POST /api/home/seen': NO_CONTENT });
    renderHook(() => useHomeVisit(MARK));
    act(() => { vi.advanceTimersByTime(30_000); });
    expect(looks(fetchMock)).toEqual([{ mark: MARK, glance: true }]);
    act(() => { show('visible'); vi.advanceTimersByTime(10_000); });
    expect(looks(fetchMock)).toHaveLength(2);
  });

  it('leaving at 5 s sends only the glance, and coming back sends a new glance', () => {
    const fetchMock = stubFetch({ 'POST /api/home/seen': NO_CONTENT });
    const first = renderHook(() => useHomeVisit(MARK));
    act(() => { vi.advanceTimersByTime(5_000); });
    first.unmount();
    act(() => { vi.advanceTimersByTime(30_000); });
    expect(looks(fetchMock)).toEqual([{ mark: MARK, glance: true }]);
    renderHook(() => useHomeVisit(MARK));
    expect(looks(fetchMock)).toEqual([{ mark: MARK, glance: true }, { mark: MARK, glance: true }]);
  });

  it('the full look sends the newest mark the server gave', () => {
    const fetchMock = stubFetch({ 'POST /api/home/seen': NO_CONTENT });
    const { rerender } = renderHook(({ mark }: { mark: string }) => useHomeVisit(mark), { initialProps: { mark: MARK } });
    rerender({ mark: LATER_MARK });
    act(() => { vi.advanceTimersByTime(10_000); });
    expect(looks(fetchMock)).toEqual([{ mark: MARK, glance: true }, { mark: LATER_MARK, glance: false }]);
  });

  it('a refused look shows nothing and never throws', async () => {
    const fetchMock = stubFetch({ 'POST /api/home/seen': () => reply({ error: 'That visit is too old.' }, 422) });
    renderHook(() => useHomeVisit(MARK));
    act(() => { vi.advanceTimersByTime(10_000); });
    await act(async () => { await Promise.resolve(); });
    expect(looks(fetchMock)).toHaveLength(2);
  });
});
