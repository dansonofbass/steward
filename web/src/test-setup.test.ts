import { describe, expect, it, vi } from 'vitest';
import { currentBook, setCurrentBook } from './api/book';
import { TEST_NOW, useFakeTimers } from './test-clock';

// In order: the first test leaves things behind; the second sees none of it (flaky-test audit S4).
describe('test-setup resets what a test leaves behind', () => {
  it('leaves fake timers, a stub, storage, another book and another date behind', () => {
    useFakeTimers();
    vi.setSystemTime(new Date(2030, 0, 1));
    vi.stubGlobal('fetch', vi.fn());
    localStorage.setItem('left', 'behind');
    setCurrentBook('margaret-ellis');
    expect(Object.prototype.hasOwnProperty.call(setTimeout, 'clock')).toBe(true);
  });

  it('starts clean, on the frozen date', () => {
    expect(Object.prototype.hasOwnProperty.call(setTimeout, 'clock')).toBe(false);
    expect(Date.now()).toBe(TEST_NOW.getTime());
    expect(localStorage.getItem('left')).toBeNull();
    expect(currentBook()).toBe('ours');
    expect(vi.isMockFunction(globalThis.fetch)).toBe(false);
  });
});
