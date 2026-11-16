import { describe, expect, it } from 'vitest';
import type { Account } from '../../api/types';
import { treatment } from './treatment';

const a = (id: number, name: string, type: Account['type'], cents: number, is_active = true): Account =>
  ({ id, name, type, owner: 'joint', source: 'manual', institution: 'Manual', is_active, balance_cents: cents, as_of: '2026-10-13', stale_days: 1 });

describe('money by tax treatment', () => {
  it('groups counted money, totals it, and lists what the plan leaves out', () => {
    const t = treatment([
      a(1, 'Checking', 'checking', 2_980_142), a(2, 'Savings', 'savings', 11_100_000), a(3, '401(k)', 'k401', 50_359_675),
      a(4, 'Roth IRA', 'roth_ira', 11_208_000), a(5, '529 — kid 1', 'plan529', 3_522_548), a(6, 'Home', 'property', 92_000_000),
      a(7, 'Mortgage', 'mortgage', -38_970_000), a(8, 'Rewards Card', 'credit', -361_038), a(9, 'Acct 9999', 'unknown', 421_200),
      a(10, 'Old savings', 'savings', 500, false),
    ]);
    expect(t.counted.map((r) => [r.name, r.cents])).toEqual([
      ['Cash', 14_080_142], ['Retirement, taxed later', 50_359_675], ['Retirement, tax-free', 11_208_000], ['College savings', 3_522_548],
    ]);
    expect(t.counted[0].sub).toBe('Checking, Savings · spend any time');
    expect(t.total).toBe(79_170_365);
    expect(t.outside.map((r) => [r.name, r.cents])).toEqual([['Home and mortgage', 53_030_000], ['Cards and loans', -361_038]]);
    expect(t.untyped).toEqual({ n: 1, cents: 421_200 });
  });

  it('lists a vehicle outside the plan', () => {
    expect(treatment([a(1, 'Subaru', 'vehicle', 2_000_000)]).outside.map((r) => [r.name, r.cents, r.sub]))
      .toEqual([['Vehicles', 2_000_000, 'Not counted: the plan never sells them']]);
  });
});
