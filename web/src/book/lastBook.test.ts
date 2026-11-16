import { afterEach, describe, expect, it } from 'vitest';
import type { BookSummary } from '../api/types';
import { pickBook, readLastBook, writeLastBook } from './lastBook';

const b = (slug: string): BookSummary => ({ slug, name: slug, kind: 'parent', role: 'manager', available: true, reason: null, owners: [], profile: null });
afterEach(() => localStorage.clear());

describe('the last-used book (ruling 4)', () => {
  it('is remembered per device and falls back to ours, then the first book', () => {
    expect(readLastBook()).toBeNull();
    writeLastBook('mom');
    expect(readLastBook()).toBe('mom');
    expect(pickBook([b('ours'), b('mom')], 'mom')?.slug).toBe('mom');
    expect(pickBook([b('ours'), b('mom')], 'gone')?.slug).toBe('ours');
    expect(pickBook([b('mom'), b('dad')], null)?.slug).toBe('mom');
    expect(pickBook([], 'mom')).toBeNull();
  });
});
