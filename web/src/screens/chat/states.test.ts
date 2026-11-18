import { describe, expect, it } from 'vitest';
import { setHouseholdZone } from '../../lib/today';
import { nextMonth, thisMonth } from './states';

// Issue #26: chat's cap date ("starts again on Dec 1") and budget pace name the household's month. At 11:00 UTC on
// Nov 30 it is already Dec 1 in Kiritimati (UTC+14) and still Nov 30 in Pago Pago (UTC-11) and on almost any device.
const LAST_OF_NOV = new Date('2026-11-30T11:00:00Z');

describe("chat's month is the household's (#26)", () => {
  it('names the 1st of the next month from the household day, not the device day', () => {
    setHouseholdZone('Pacific/Kiritimati');
    expect(nextMonth(LAST_OF_NOV)).toBe('Jan 1');
    setHouseholdZone('Pacific/Pago_Pago');
    expect(nextMonth(LAST_OF_NOV)).toBe('Dec 1');
  });

  it("gives the household month's name, day and length for the pace", () => {
    setHouseholdZone('Pacific/Kiritimati');
    expect(thisMonth(LAST_OF_NOV)).toEqual({ name: 'December', day: 1, days: 31 });
    setHouseholdZone('Pacific/Pago_Pago');
    expect(thisMonth(LAST_OF_NOV)).toEqual({ name: 'November', day: 30, days: 30 });
  });

  it('rolls over the year and knows February', () => {
    setHouseholdZone('UTC');
    expect(nextMonth(new Date('2026-12-31T12:00:00Z'))).toBe('Jan 1');
    expect(thisMonth(new Date('2028-02-10T12:00:00Z'))).toEqual({ name: 'February', day: 10, days: 29 });
  });
});
