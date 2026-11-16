import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useFakeTimers } from '../test-clock';
import { ApiError } from '../api/client';
import { DEBOUNCE_MS, useDebouncedRequest, type Request } from './useDebouncedRequest';

beforeEach(() => { useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

function deferred<T>() {
  let resolve!: (v: T) => void;
  const p = new Promise<T>((r) => { resolve = r; });
  return { p, resolve };
}
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });

describe('useDebouncedRequest', () => {
  it('waits 150 ms after the last change and sends only the newest request', async () => {
    expect(DEBOUNCE_MS).toBe(150);
    const run = vi.fn(async () => 'answer');
    const { result, rerender } = renderHook(({ k }: { k: string }) => useDebouncedRequest<string>({ key: k, run }), { initialProps: { k: 'a' } });
    rerender({ k: 'b' });
    await act(async () => { vi.advanceTimersByTime(100); });
    rerender({ k: 'c' });
    await act(async () => { vi.advanceTimersByTime(149); });
    expect(run).not.toHaveBeenCalled();
    expect(result.current.pending).toBe(true);
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(run).toHaveBeenCalledTimes(1);
    await flush();
    expect(result.current).toMatchObject({ key: 'c', data: 'answer', pending: false, error: null });
  });

  it('a newer key aborts the one in flight and drops its late answer', async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const signals: AbortSignal[] = [];
    const runFor = (d: { p: Promise<string> }) => (s: AbortSignal) => { signals.push(s); return d.p; };
    const { result, rerender } = renderHook(({ req }: { req: Request<string> }) => useDebouncedRequest<string>(req), {
      initialProps: { req: { key: 'a', run: runFor(first) } as Request<string> },
    });
    await act(async () => { vi.advanceTimersByTime(DEBOUNCE_MS); });
    expect(signals).toHaveLength(1);
    rerender({ req: { key: 'b', run: runFor(second) } });
    expect(signals[0].aborted).toBe(true);
    await act(async () => { vi.advanceTimersByTime(DEBOUNCE_MS); });
    second.resolve('new');
    await flush();
    first.resolve('old');
    await flush();
    expect(result.current).toMatchObject({ key: 'b', data: 'new' });
  });

  it('reports a real error for its key and keeps the last good data', async () => {
    let fail = false;
    const run = vi.fn(async () => { if (fail) throw new ApiError(422, 'Spending in retirement must be a whole number.'); return 'good'; });
    const { result, rerender } = renderHook(({ k }: { k: string }) => useDebouncedRequest<string>({ key: k, run }), { initialProps: { k: 'a' } });
    await act(async () => { vi.advanceTimersByTime(DEBOUNCE_MS); });
    await flush();
    fail = true;
    rerender({ k: 'b' });
    await act(async () => { vi.advanceTimersByTime(DEBOUNCE_MS); });
    await flush();
    expect(result.current.key).toBe('b');
    expect((result.current.error as Error).message).toBe('Spending in retirement must be a whole number.');
    expect(result.current.data).toBe('good');
    expect(result.current.pending).toBe(false);
  });

  it('sends nothing for a null request', async () => {
    const { result } = renderHook(() => useDebouncedRequest<string>(null));
    await act(async () => { vi.advanceTimersByTime(1000); });
    expect(result.current).toMatchObject({ key: null, data: undefined, pending: false });
  });
});
