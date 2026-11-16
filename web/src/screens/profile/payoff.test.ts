import { describe, expect, it } from 'vitest';
import { payoff, payoffYmd, thisMonth } from './payoff';

const OCT_2026 = { year: 2026, month: 10 };

describe('payoff (carried decision: calculated, with an override)', () => {
  it('works out the mockup household: $571,300 at 2.875% paying $2,680 is 299 payments, last in September 2051', () => {
    expect(payoff(57_130_000, 2875, 268_000, OCT_2026)).toEqual({ kind: 'months', payments: 299, year: 2051, month: 9 });
  });
  it('matches a standard 30-year loan: $200,000 at 6% paying $1,199.11 is 360 payments', () => {
    expect(payoff(20_000_000, 6000, 119_911, OCT_2026)).toEqual({ kind: 'months', payments: 360, year: 2056, month: 10 });
  });
  it('one cent short of the exact $1,199.10 payment needs one more payment', () => {
    expect(payoff(20_000_000, 6000, 119_910, OCT_2026)).toMatchObject({ payments: 361, year: 2056, month: 11 });
  });
  it('a 0% loan divides evenly, rounding the last part up', () => {
    expect(payoff(10_000_000, 0, 100_000, OCT_2026)).toMatchObject({ kind: 'months', payments: 100 });
    expect(payoff(10_000_000, 0, 99_900, OCT_2026)).toMatchObject({ kind: 'months', payments: 101 });
  });
  it('never pays off when the payment does not cover the interest', () => {
    expect(payoff(30_000_000, 6000, 150_000, OCT_2026)).toEqual({ kind: 'never' });   // interest is exactly $1,500
    expect(payoff(30_000_000, 6000, 140_000, OCT_2026)).toEqual({ kind: 'never' });
    expect(payoff(30_000_000, 6000, 0, OCT_2026)).toEqual({ kind: 'never' });
  });
  it('a zero balance is already paid off', () => {
    expect(payoff(0, 3000, 100_000, OCT_2026)).toEqual({ kind: 'paid_off' });
  });
  it('rolls over into the next year', () => {
    expect(payoff(10_000, 0, 10_000, { year: 2026, month: 12 })).toEqual({ kind: 'months', payments: 1, year: 2027, month: 1 });
  });
  it('stores the 1st of the month and reads the current month', () => {
    expect(payoffYmd({ year: 2051, month: 9 })).toBe('2051-09-01');
    expect(thisMonth(new Date(2026, 9, 14))).toEqual(OCT_2026);
  });
});
