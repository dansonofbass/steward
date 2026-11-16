// Unit-test helpers only; nothing in the app imports this file.
import { vi } from 'vitest';

/** Every test starts on this date (test-setup.ts), the same instant as Python's DEFAULT_NOW in the household's zone.
 *  A test that needs another date sets it with vi.setSystemTime. */
export const TEST_NOW = new Date(2026, 9, 30, 12, 0);

/** test-setup's beforeEach: Date frozen at TEST_NOW, and the timers real. */
export function freezeDate(): void {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(TEST_NOW);
}

/** Fake timers for this test, on the date it already has. Use it instead of vi.useFakeTimers, which does nothing
 *  while test-setup's Date fake is installed. Never pass shouldAdvanceTime: it ties fake time back to real time. */
export function useFakeTimers(config?: Parameters<typeof vi.useFakeTimers>[0]): void {
  const now = Date.now();
  vi.useRealTimers();
  vi.useFakeTimers(config);
  vi.setSystemTime(now);
}

/** Testing Library waits by advancing fake time when it sees Jest's fake timers: setTimeout.clock, which Vitest's
 *  fake timers set, and a global `jest`, which this provides. So findBy and waitFor work under fake timers, and their
 *  ceiling is fake time, not the machine's load (flaky-test audit S3). Testing Library already wraps each advance in
 *  act (its unstable_advanceTimersWrapper), so wait on the screen with its waitFor, never vi.waitFor: Vitest's waits
 *  outside act, and the updates that land meanwhile print "not wrapped in act". */
export function letTestingLibraryDriveFakeTimers(): void {
  (globalThis as { jest?: unknown }).jest = { advanceTimersByTime: (ms: number) => { vi.advanceTimersByTime(ms); } };
}
