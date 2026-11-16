import { describe, expect, it } from 'vitest';
import { parseMode, rangeFor, ymd } from './dates';

const d = (y: number, m: number, day: number) => new Date(y, m - 1, day, 23, 30);

describe('rangeFor', () => {
  it('last 7 days is today minus six through today, in local time', () => {
    expect(rangeFor('7', d(2026, 10, 13))).toEqual({ from: '2026-10-07', to: '2026-10-13' });
  });
  it('last 7 days crosses a month and a year boundary', () => {
    expect(rangeFor('7', d(2026, 10, 3))).toEqual({ from: '2026-09-27', to: '2026-10-03' });
    expect(rangeFor('7', d(2027, 1, 2))).toEqual({ from: '2026-12-27', to: '2027-01-02' });
  });
  it('last 30 days is today minus 29 through today, leap day included', () => {
    expect(rangeFor('30', d(2026, 10, 13))).toEqual({ from: '2026-09-14', to: '2026-10-13' });
    expect(rangeFor('30', d(2028, 3, 5))).toEqual({ from: '2028-02-05', to: '2028-03-05' });
  });
  it('this month starts on the first, even on the first', () => {
    expect(rangeFor('month', d(2026, 10, 13))).toEqual({ from: '2026-10-01', to: '2026-10-13' });
    expect(rangeFor('month', d(2026, 11, 1))).toEqual({ from: '2026-11-01', to: '2026-11-01' });
  });
  it('all time clears both', () => {
    expect(rangeFor('all', d(2026, 10, 13))).toEqual({});
  });
  it('custom passes the URL values through and drops blanks', () => {
    expect(rangeFor('custom', d(2026, 10, 13), { from: '2020-01-01', to: '' })).toEqual({ from: '2020-01-01', to: undefined });
  });
});

describe('parseMode', () => {
  it('defaults to 7 for missing or unknown values', () => {
    expect(parseMode(null)).toBe('7');
    expect(parseMode('nope')).toBe('7');
    expect(parseMode('all')).toBe('all');
  });
});

it('ymd pads', () => { expect(ymd(new Date(2026, 0, 5))).toBe('2026-01-05'); });
