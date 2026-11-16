import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { crossedMilestone, firstMaxed, forgetJoy, MILESTONE_KEY, milestoneAt } from './joy';

beforeEach(() => { localStorage.clear(); forgetJoy(); });
afterEach(() => vi.restoreAllMocks());

describe('once per device (investment views spec, Joy)', () => {
  it('milestones go by $100k up to $1M, then by $250k', () => {
    expect([9_999_999, 10_000_000, 99_999_999, 100_000_000, 112_000_000, 125_000_000].map(milestoneAt))
      .toEqual([0, 10_000_000, 90_000_000, 100_000_000, 100_000_000, 125_000_000]);
  });

  it('the first look records where net worth stands; a higher milestone later cheers once, and a dip and a rise do not', () => {
    expect(crossedMilestone(95_000_000)).toBeNull();
    expect(localStorage.getItem(MILESTONE_KEY)).toBe('90000000');
    expect(crossedMilestone(99_000_000)).toBeNull();
    expect(crossedMilestone(100_500_000)).toBe(100_000_000);
    expect(crossedMilestone(100_600_000)).toBeNull();
    expect(crossedMilestone(80_000_000)).toBeNull();
    expect(crossedMilestone(101_000_000)).toBeNull();
  });

  it('a limit reached cheers once per owner, kind and year', () => {
    expect(firstMaxed('jr:k401:2026')).toBe(true);
    expect(firstMaxed('jr:k401:2026')).toBe(false);
    expect(firstMaxed('jr:k401:2027')).toBe(true);
  });

  it('with storage blocked, it still cheers only once this visit', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(crossedMilestone(95_000_000)).toBeNull();
    expect(crossedMilestone(100_500_000)).toBe(100_000_000);
    expect(crossedMilestone(100_500_000)).toBeNull();
    expect(firstMaxed('jr:ira:2026')).toBe(true);
    expect(firstMaxed('jr:ira:2026')).toBe(false);
  });
});
