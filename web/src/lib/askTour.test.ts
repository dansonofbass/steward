import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resetTourLoad, tourDone, tourDue, tourShown } from './askTour';

beforeEach(() => { localStorage.clear(); resetTourLoad(); });
afterEach(() => { vi.restoreAllMocks(); });

describe('the first-use tip mark (P23)', () => {
  it('is per person on this device', () => {
    expect(tourDue(1)).toBe(true);
    tourDone(1);
    expect(tourDue(1)).toBe(false);
    expect(tourDue(2)).toBe(true);
    expect(localStorage.getItem('steward-ask-tour:1')).toBe('done');
  });
  it('when storage throws, it shows at most once per page load and never throws itself', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(tourDue(1)).toBe(true);
    tourShown();
    expect(tourDue(1)).toBe(false);
    expect(() => tourDone(1)).not.toThrow();
  });
});
