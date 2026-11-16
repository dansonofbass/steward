import { describe, expect, it } from 'vitest';
import { dateLabel, dateLabelFromIso, dollars, localYmd, money, moneyParts, monthLabel, monthYear, relativeDays } from './format';

const today = new Date('2026-10-13T12:00:00-07:00');

describe('money', () => {
  it('formats cents with a true minus and tabular-friendly digits', () => {
    expect(money(-5412)).toBe('−$54.12');
    expect(money(123456789)).toBe('$1,234,567.89');
    expect(money(0)).toBe('$0.00');
    expect(money(5, { sign: 'always' })).toBe('+$0.05');
    expect(money(-5, { sign: 'never' })).toBe('$0.05');
  });
  it('compacts only when asked', () => {
    expect(money(125700000, { compact: true })).toBe('$1.26M');
    expect(money(125700000)).toBe('$1,257,000.00');
    expect(money(950000, { compact: true })).toBe('$9,500');
  });
  it('splits into parts', () => {
    expect(moneyParts(-5412)).toEqual({ sign: '−', dollars: '54', cents: '12' });
    expect(moneyParts(123456789)).toEqual({ sign: '', dollars: '1,234,567', cents: '89' });
  });
});

describe('dates', () => {
  it('relative days in plain words', () => {
    expect(relativeDays('2026-10-13', today)).toBe('Today');
    expect(relativeDays('2026-10-12', today)).toBe('Yesterday');
    expect(relativeDays('2026-10-10', today)).toBe('3 days ago');
    expect(relativeDays(null, today)).toBe('Not yet');
  });
  it('labels drop the year only for this year', () => {
    expect(dateLabel('2026-10-12', today)).toBe('Oct 12');
    expect(dateLabel('2025-10-12', today)).toBe('Oct 12, 2025');
    expect(monthLabel('2026-10-01')).toBe('October 2026');
    expect(monthYear(2027, 6)).toBe('Jun 2027');
  });
});

describe('timestamps in local time', () => {
  it('uses the local day, not the UTC day', () => {
    const early = new Date(2026, 9, 13, 1, 0); // 01:00 local; in zones east of UTC the UTC date is Oct 12
    expect(localYmd(early.toISOString())).toBe('2026-10-13');
    expect(dateLabelFromIso(early.toISOString(), new Date(2026, 9, 20))).toBe('Oct 13');
  });
});

describe('dollars', () => {
  it('rounds to whole dollars with a true minus sign', () => {
    expect(dollars(476012)).toBe('$4,760');
    expect(dollars(-9950)).toBe('−$100');
    expect(dollars(0)).toBe('$0');
    expect(dollars(48000, { sign: 'always' })).toBe('+$480');
  });
});
