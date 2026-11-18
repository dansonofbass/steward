import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clearJoy, crossedMilestone, firstMaxed, forgetJoy, joyScope, MAXED_KEY, MILESTONE_KEY, milestoneAt } from './joy';

beforeEach(() => { localStorage.clear(); forgetJoy(); });
afterEach(() => vi.restoreAllMocks());

const JR = joyScope(1, 'ours');
const SAM = joyScope(2, 'ours');

describe('once per device (investment views spec, Joy)', () => {
  it('milestones go by $100k up to $1M, then by $250k', () => {
    expect([9_999_999, 10_000_000, 99_999_999, 100_000_000, 112_000_000, 125_000_000].map(milestoneAt))
      .toEqual([0, 10_000_000, 90_000_000, 100_000_000, 100_000_000, 125_000_000]);
  });

  it('the first look records where net worth stands; a higher milestone later cheers once, and a dip and a rise do not', () => {
    expect(crossedMilestone(JR, 95_000_000)).toBeNull();
    expect(localStorage.getItem(`${MILESTONE_KEY}:1:ours`)).toBe('90000000');
    expect(crossedMilestone(JR, 99_000_000)).toBeNull();
    expect(crossedMilestone(JR, 100_500_000)).toBe(100_000_000);
    expect(crossedMilestone(JR, 100_600_000)).toBeNull();
    expect(crossedMilestone(JR, 80_000_000)).toBeNull();
    expect(crossedMilestone(JR, 101_000_000)).toBeNull();
  });

  it('a limit reached cheers once per owner, kind and year', () => {
    expect(firstMaxed(JR, 'jr:k401:2026')).toBe(true);
    expect(firstMaxed(JR, 'jr:k401:2026')).toBe(false);
    expect(firstMaxed(JR, 'jr:k401:2027')).toBe(true);
  });

  it('with storage blocked, it still cheers only once this visit', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(crossedMilestone(JR, 95_000_000)).toBeNull();
    expect(crossedMilestone(JR, 100_500_000)).toBe(100_000_000);
    expect(crossedMilestone(JR, 100_500_000)).toBeNull();
    expect(firstMaxed(JR, 'jr:ira:2026')).toBe(true);
    expect(firstMaxed(JR, 'jr:ira:2026')).toBe(false);
  });
});

describe('kept per person and book, and gone at sign-out (issue #6)', () => {
  it("a second member on the same device has their own first look, so the first one's milestone neither skips nor plays their cheer", () => {
    expect(crossedMilestone(JR, 95_000_000)).toBeNull();
    expect(crossedMilestone(JR, 100_500_000)).toBe(100_000_000);
    expect(crossedMilestone(SAM, 100_500_000)).toBeNull();            // Sam's first look only records
    expect(crossedMilestone(SAM, 112_000_000)).toBeNull();
    expect(crossedMilestone(SAM, 125_000_000)).toBe(125_000_000);
    expect(crossedMilestone(joyScope(1, 'parent-book'), 30_000_000)).toBeNull();
    expect(firstMaxed(JR, 'jr:k401:2026')).toBe(true);
    expect(firstMaxed(SAM, 'jr:k401:2026')).toBe(true);
  });

  it('nothing is read, kept or cheered before it is known who is signed in and in which book', () => {
    expect(joyScope(undefined, 'ours')).toBeNull();
    expect(joyScope(1, null)).toBeNull();
    expect(crossedMilestone(null, 100_500_000)).toBeNull();
    expect(firstMaxed(null, 'jr:k401:2026')).toBe(false);
    expect(localStorage.length).toBe(0);
  });

  it("clearJoy removes every person's milestone and maxed keys, the old unscoped ones too, and leaves the device's own settings", () => {
    localStorage.setItem(MILESTONE_KEY, '90000000');
    localStorage.setItem(MAXED_KEY, '["jr:k401:2026"]');
    localStorage.setItem('steward-swipe', 'off');
    crossedMilestone(JR, 95_000_000);
    firstMaxed(SAM, 'jr:k401:2026');
    clearJoy();
    expect(Object.keys(localStorage)).toEqual(['steward-swipe']);
    expect(crossedMilestone(JR, 100_500_000)).toBeNull();              // forgotten in memory too: a first look again
  });

  it('a first look drops the unscoped keys an earlier version left', () => {
    localStorage.setItem(MILESTONE_KEY, '90000000');
    localStorage.setItem(MAXED_KEY, '["jr:k401:2026"]');
    crossedMilestone(JR, 95_000_000);
    firstMaxed(JR, 'jr:k401:2026');
    expect(localStorage.getItem(MILESTONE_KEY)).toBeNull();
    expect(localStorage.getItem(MAXED_KEY)).toBeNull();
  });
});
