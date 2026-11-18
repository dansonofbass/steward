import { afterEach, describe, expect, it } from 'vitest';
import { dateLabel, dateLabelFromIso, localYmd, relativeDays } from './format';
import { addDays, clockTime, dayOf, daysBetween, forgetHouseholdZone, householdZone, setHouseholdZone, thisYear, today } from './today';

// Two zones a day apart at this instant, whatever zone the machine running the test is in.
const NOON_UTC = new Date('2026-11-16T12:00:00Z');    // Kiritimati (UTC+14): Nov 17, 2 AM; Pago Pago (UTC-11): Nov 16, 1 AM
afterEach(forgetHouseholdZone);

describe("the household's today (issue #26)", () => {
  it("is the household's calendar day, not the device's", () => {
    setHouseholdZone('Pacific/Kiritimati');
    expect(today(NOON_UTC)).toBe('2026-11-17');
    setHouseholdZone('Pacific/Pago_Pago');
    expect(today(NOON_UTC)).toBe('2026-11-16');
    expect(dayOf('2026-11-16T12:00:00Z')).toBe('2026-11-16');
    expect(dayOf(NOON_UTC.getTime())).toBe('2026-11-16');
  });

  it("falls back to the device's zone when /me names none, or one the browser doesn't know", () => {
    const device = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    expect(today(NOON_UTC)).toBe(device(NOON_UTC));
    setHouseholdZone('Nowhere/Atall');
    expect(householdZone()).toBeUndefined();
    expect(today(NOON_UTC)).toBe(device(NOON_UTC));
  });

  it('moves by calendar days across month ends, years and clock changes', () => {
    expect(addDays('2026-11-01', -1)).toBe('2026-10-31');
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01');
    expect(addDays('2026-03-08', 1)).toBe('2026-03-09');
    expect(daysBetween('2026-10-31', '2026-11-02')).toBe(2);
    expect(daysBetween('2026-11-02', '2026-10-31')).toBe(-2);
  });

  it("gives the year and the clock time on the household's clock", () => {
    setHouseholdZone('Pacific/Kiritimati');
    expect(thisYear(new Date('2026-12-31T12:00:00Z'))).toBe(2027);
    expect(clockTime(NOON_UTC)).toBe('2:00 AM');
  });

  it('drives every relative label and day in lib/format', () => {
    setHouseholdZone('Pacific/Kiritimati');
    // At noon UTC on Nov 16 it is already Nov 17 at home, so a balance dated Nov 17 is today's, not tomorrow's.
    expect(relativeDays('2026-11-17', NOON_UTC)).toBe('Today');
    expect(relativeDays('2026-11-16', NOON_UTC)).toBe('Yesterday');
    expect(localYmd('2026-11-16T12:00:00Z')).toBe('2026-11-17');
    expect(dateLabel('2027-01-02', new Date('2026-12-31T12:00:00Z'))).toBe('Jan 2');
    setHouseholdZone('Pacific/Pago_Pago');
    expect(relativeDays('2026-11-15', NOON_UTC)).toBe('Yesterday');
    expect(relativeDays('2026-11-16', '2026-11-18')).toBe('2 days ago');
  });

  it('reads an empty or malformed timestamp as no day, never a RangeError mid-render', () => {
    setHouseholdZone('Pacific/Kiritimati');
    expect(localYmd('')).toBe('');
    expect(dayOf('not a time')).toBe('');
    expect(clockTime('')).toBe('');
    expect(dateLabelFromIso('', NOON_UTC)).toBe('');
    expect(dateLabel('', '2026-11-16')).toBe('');
  });
});
