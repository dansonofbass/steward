import { describe, expect, it } from 'vitest';
import type { Account } from '../../api/types';
import type { PlanMoves, PlanOneOff } from './api';
import { isStale, lastUpdatedRows, oneOffsBullet, yearlyBullet } from './HowItWorks';
import { moveRows } from './Moves';

describe('What moves your plan most (P27)', () => {
  const base: PlanMoves = { ss_at_67: { jr_cents: 335_400, spouse_cents: null }, retirement_spending_cents: 740_000, mortgage_payoff_year: null,
    health_premium_cents: 1_680_000, college: { count: 0, level: null }, saving_cents: 215_000 };
  const names = { jr: 'JR', spouse: 'Sam', joint: 'Joint' };
  const value = (m: PlanMoves, label: string) => moveRows(m, names).find((r) => r.label === label)?.value;
  it('one person at 67, no mortgage row once paid off, no college row without kids', () => {
    expect(moveRows(base, names).map((r) => r.label)).toEqual(['Social Security at 67', 'Spending in retirement', 'Health before Medicare', 'Saving now']);
    expect(value(base, 'Social Security at 67')).toBe('$3,354 a month');
    expect(value({ ...base, ss_at_67: { jr_cents: null, spouse_cents: null } }, 'Social Security at 67')).toBe('not added');
  });
  it('college says the kids and their level only when they share one', () => {
    expect(value({ ...base, college: { count: 1, level: 'private' } }, 'College')).toBe('1 kid · private');
    expect(value({ ...base, college: { count: 3, level: null } }, 'College')).toBe('3 kids');
    expect(value({ ...base, college: { count: 2, level: 'two_year' } }, 'College')).toBe('2 kids · trade or community college');
  });
});

describe('How this works', () => {
  it('flags stale inputs', () => {
    expect(isStale("Taxable's balance was last updated 120 days ago.")).toBe(true);
    expect(isStale('Acme Stable Value Fund has no holdings listed, so it uses the default mix for its type.')).toBe(true);
    expect(isStale('Funds on a default mix (no built-in asset class): ZZFUNDX.')).toBe(true);
    expect(isStale('Based on 7 months of spending history, annualized.')).toBe(true);
    expect(isStale('Social Security benefits are cut 17% from 2034 (2026 Trustees Report).')).toBe(false);
  });
  it('lists when each input was last updated, and which Profile section changes it', () => {
    const acct = { id: 1, name: 'Checking', type: 'checking', owner: 'joint', source: 'simplefin', institution: 'Big Bank', is_active: true, balance_cents: 1, as_of: '2026-10-13', stale_days: 1 } as Account;
    const rows = lastUpdatedRows({
      accounts: [acct], factsAsOf: { 'jr.salary_cents': '2026-10-12', 'health.premium_cents': '2026-10-12' },
      earnings: { jr: { years: 19, first_year: 2007, last_year: 2025, imported_at: '2026-10-12T18:00:00+00:00' }, spouse: null },
      names: { jr: 'JR', spouse: 'Sam', joint: 'Joint' }, childCount: 3, spendingMonths: 7, today: new Date(2026, 9, 14),
      setAsides: { updated_at: null, updated_by: null, yearly_count: 0, one_offs: [] },
    });
    expect(rows.map((r) => [r.label, r.value, r.section ?? null, !!r.warn])).toEqual([
      ['Account balances', 'Yesterday', null, false],
      ['Pay', 'Oct 12', 'you', false],
      ['Earnings records', expect.stringMatching(/^JR Oct 1[23] · Sam not added$/), 'benefits', false],
      ['Kids and college', '3 children', 'kids', false],
      ['Health insurance', 'Oct 12', 'benefits', false],
      ['Spending history', '7 months', null, true],
      ['Set-asides', 'not added', null, false],
    ]);
  });
});

describe('How this works, with set-asides (11c)', () => {
  const one_offs: PlanOneOff[] = [
    { id: 6, name: 'Water heater', year: 2028, due_year: 2028, due_month: 12, overdue: false, cents: 220_000, monthly_cents: 8_500, is_estimate: true },
    { id: 7, name: 'Roof', year: 2032, due_year: 2032, due_month: 12, overdue: false, cents: 1_800_000, monthly_cents: 24_300, is_estimate: false },
  ];
  it('words the two bullets', () => {
    expect(yearlyBullet(5)).toBe('Yearly costs you set aside, like property tax and car insurance, are already in the spending history and are not listed. Property tax counts there even though it sits under Taxes on Spending. Income tax is left out: the plan works that out itself.');
    expect(yearlyBullet(0)).toBeNull();
    expect(oneOffsBullet(one_offs)).toBe('Big one-off costs you are setting aside are not part of your spending; each comes out in its year: Water heater, 2028, $2,200 (estimate); Roof, 2032, $18,000.');
    expect(oneOffsBullet([one_offs[0]])).toBe('A big one-off cost you are setting aside is not part of your spending; it comes out in its year: Water heater, 2028, $2,200 (estimate).');
    // With no yearly set-asides the one-offs bullet stands alone.
    expect(yearlyBullet(0)).toBeNull();
    expect(oneOffsBullet([])).toBeNull();
  });
  it('lists when set-asides last changed', () => {
    const base = { accounts: [], factsAsOf: {}, earnings: undefined, names: { jr: 'JR', spouse: 'Sam', joint: 'Joint' }, childCount: 0, spendingMonths: 12, today: new Date(2026, 9, 26) };
    const rows = lastUpdatedRows({ ...base, setAsides: { updated_at: '2026-10-25T19:00:00+00:00', updated_by: 'JR', yearly_count: 5, one_offs } });
    expect(rows.at(-1)).toEqual({ label: 'Set-asides', value: 'Oct 25, by JR · 2 one-offs in the plan', to: '/spending/setasides' });
    expect(lastUpdatedRows({ ...base, setAsides: { updated_at: null, updated_by: null, yearly_count: 0, one_offs: [] } }).at(-1)!.value).toBe('not added');
    expect(lastUpdatedRows({ ...base, setAsides: { updated_at: '2026-10-25T19:00:00+00:00', updated_by: null, yearly_count: 1, one_offs: [one_offs[0]] } }).at(-1)!.value).toBe('Oct 25 · 1 one-off in the plan');
  });
});
