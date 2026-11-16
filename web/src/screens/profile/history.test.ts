import { describe, expect, it } from 'vitest';
import { factText, historyLine, sectionFacts } from './history';

const names = { jr: 'JR', spouse: 'Alex', joint: 'Joint' };

describe('earlier values', () => {
  it('lists the facts each section writes, with plain labels', () => {
    expect(sectionFacts('home', names)!.map((f) => f.key)).toEqual(['home.value_cents', 'mortgage.rate_bp', 'mortgage.payment_cents', 'mortgage.payoff_date']);
    expect(sectionFacts('you', names)!.map((f) => f.label).slice(0, 4)).toEqual(["JR's birthday", "Alex's birthday", 'State', 'Filing status']);
    expect(sectionFacts('you', names)![4].label).toBe("JR's yearly salary, before deductions");
    expect(sectionFacts('benefits', names)!.map((f) => f.key)).toEqual(['health.premium_cents']);
    expect(sectionFacts('banks', names)).toBeNull();
    expect(sectionFacts('kids', names)).toBeNull();
  });
  it('shows each kind of stored value in plain words', () => {
    expect(factText('rate', '287.5')).toBe('2.875%');
    expect(factText('dollars', '125000000')).toBe('$1,250,000');
    expect(factText('percent', '800')).toBe('8%');
    expect(factText('month', '2051-09-01')).toBe('September 2051');
    expect(factText('date', '1984-03-12')).toBe('Mar 12, 1984');
    expect(factText('state', 'CA')).toBe('California');
    expect(factText('filing', 'mfj')).toBe('Married filing jointly');
  });
  it('one line per earlier value: the value, when, and who saved it', () => {
    expect(historyLine('dollars', { value: '125000000', as_of: '2026-10-14', note: 'Saved by JR' }, new Date(2026, 9, 14)))
      .toBe('$1,250,000 · Oct 14 · Saved by JR');
    expect(historyLine('dollars', { value: '120000000', as_of: '2025-03-02', note: null }, new Date(2026, 9, 14)))
      .toBe('$1,200,000 · Mar 2, 2025');
  });
});
