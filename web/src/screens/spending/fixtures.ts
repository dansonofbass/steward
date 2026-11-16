// Test data only: the mockups' household (web/mockups/spending.js), as the API would answer. Nothing in the app imports it.
import type { EverydayRow, FixedRow, SpendingKind, SpendingMonth, SpendingTargets, SpendingTrends, TargetRow, TrendRow } from '../../api/types';

const lvl = (spent: number, target: number | null): EverydayRow['over_level'] => {
  if (target === null) return null;
  const over = spent - target;
  return over < 500 ? 'on' : over <= 2500 || over * 10 <= target ? 'little' : 'clear';
};
const ev = (category: string, target: number | null, spent: number, state: EverydayRow['state'], typical: number | null,
  order: number, usual: number | null = null, refunds = 0): EverydayRow =>
  ({ category, kind: 'everyday', target_cents: target, spent_cents: spent, refunds_cents: refunds, usual_by_today_cents: usual, state,
    over_cents: target === null ? null : Math.max(0, spent - target), over_level: lvl(spent, target), typical_cents: typical, order });
const fx = (category: string, kind: FixedRow['kind'], usual: number, spent: number, state: FixedRow['state'], tone: FixedRow['tone'],
  on: string | null, merchant: string | null, day: number | null, new_payee: FixedRow['new_payee'] = null): FixedRow =>
  ({ category, kind, expected: true, expected_cents: usual, usual_cents: usual, spent_cents: spent, refunds_cents: 0, state, tone,
    came_out_on: on, merchant, typical_day: day, new_payee });
/** Every spending category's kind (the server's DEFAULT_KINDS, with Kids saved as Flexible). */
export const KINDS: Record<string, SpendingKind> = {
  groceries: 'everyday', dining: 'everyday', housing: 'fixed', utilities: 'fixed', transport: 'everyday', travel: 'everyday',
  health: 'everyday', insurance: 'fixed', loan_payments: 'fixed', childcare_education: 'commitment', giving: 'commitment',
  subscriptions: 'fixed', shopping: 'everyday', personal: 'everyday', cash_atm: 'everyday', kids: 'everyday', pets: 'everyday',
  home: 'everyday', gifts: 'everyday', entertainment: 'everyday', business_expense: 'everyday', taxes: 'occasional', fees: 'everyday',
};

export const OCT: SpendingMonth = {
  month: '2026-10', as_of: '2026-10-25', current: true, day: 25, days: 31, days_left: 6, earliest: '2024-10',
  head: { spent_cents: 797_400, planned_cents: 814_000, everyday_spent_cents: 339_100, everyday_target_cents: 355_000,
    fixed_spent_cents: 458_300, fixed_expected_cents: 459_000, fixed_more_cents: 0, fixed_not_yet: 0, fixed_summary: 'plain',
    occasional_cents: 0, money_out_cents: 797_400, income_cents: 1_025_400, money_in_cents: 1_025_400, set_aside_cents: 0, paid_from_set_aside_cents: 0 },
  everyday: [
    ev('groceries', 130_000, 104_000, 'on_track', 124_000, 0, 104_839),
    ev('dining', 50_000, 46_800, 'on_track', 47_000, 1, 40_323, 1_384),
    ev('transport', 45_000, 33_200, 'on_track', 44_000, 2, 36_290),
    ev('shopping', 40_000, 51_200, 'over', 39_000, 3, 32_258),
    ev('home', 30_000, 24_800, 'on_track', 29_000, 4, 24_194),
    ev('kids', 25_000, 19_000, 'on_track', 23_000, 5, 20_161),
    ev('health', 20_000, 14_000, 'on_track', 18_000, 6, 16_129),
    ev('entertainment', 15_000, 9_600, 'on_track', 12_000, 7, 12_097),
    ev('personal', null, 8_400, 'none', 9_000, 8),
    ev('gifts', null, 4_500, 'none', 6_000, 9),
  ],
  not_sorted: { count: 7, cents: 23_600 },
  fixed: [
    fx('housing', 'fixed', 268_000, 268_000, 'as_usual', 'check', '2026-10-01', 'Home loan', 1),
    fx('utilities', 'fixed', 41_000, 39_500, 'as_usual', 'check', '2026-10-12', 'City Power & Light', 12),
    fx('insurance', 'fixed', 36_000, 36_000, 'as_usual', 'check', '2026-10-05', 'Safeguard Insurance', 5),
    fx('subscriptions', 'fixed', 12_000, 12_800, 'as_usual', 'amber', '2026-10-03', 'Streamflix', 3, { name: 'StreamBox', cents: 799 }),
    fx('childcare_education', 'commitment', 82_000, 82_000, 'as_usual', 'check', '2026-10-02', 'Little Sprouts', 2),
    { ...fx('giving', 'commitment', 20_000, 20_000, 'as_usual', 'check', '2026-10-03', 'Grace Community', 3), outside_cents: 0 },
  ],
  occasional: [],
  income: [{ category: 'income', cents: 1_024_000 }, { category: 'interest', cents: 1_400 }],
  target_check: null,
  has_targets: true, set_aside: null, kinds: KINDS,
};

export const SEP: SpendingMonth = {
  ...OCT, month: '2026-09', as_of: '2026-10-25', current: false, day: null, days: 30, days_left: null,
  head: { ...OCT.head, spent_cents: 831_200, everyday_spent_cents: 372_200, fixed_spent_cents: 459_000, fixed_summary: 'plain' as const, fixed_not_yet: 0, money_out_cents: 831_200, income_cents: 1_024_000, money_in_cents: 1_024_000 },
  everyday: [
    ev('groceries', 130_000, 122_000, 'on_track', 124_000, 0), ev('dining', 50_000, 49_000, 'on_track', 47_000, 1),
    ev('transport', 45_000, 45_500, 'over', 44_000, 2), ev('shopping', 40_000, 44_000, 'over', 39_000, 3),
    ev('home', 30_000, 29_000, 'on_track', 29_000, 4), ev('kids', 25_000, 23_000, 'on_track', 23_000, 5),
    ev('health', 20_000, 9_500, 'on_track', 18_000, 6), ev('entertainment', 15_000, 8_500, 'on_track', 12_000, 7),
    ev('personal', null, 9_000, 'none', 9_000, 8), ev('gifts', null, 6_000, 'none', 6_000, 9),
  ],
  not_sorted: { count: 9, cents: 26_700 },
  fixed: OCT.fixed.map((f) => ({ ...f, state: 'as_usual' as const, tone: 'check' as const, spent_cents: f.usual_cents ?? 0, new_payee: null,
    came_out_on: f.came_out_on ? f.came_out_on.replace('2026-10', '2026-09') : null })),
  income: [{ category: 'income', cents: 1_024_000 }],
};

const MONTHS = ['2025-11', '2025-12', '2026-01', '2026-02', '2026-03', '2026-04', '2026-05', '2026-06', '2026-07', '2026-08', '2026-09', '2026-10'];
const tr = (category: string, kind: TrendRow['kind'], group: TrendRow['group'], target: number | null, expected: number | null,
  typical: number | null, spent: number[], over_in: number, order: number): TrendRow =>
  ({ category, kind, group, target_cents: target, expected_cents: expected, typical_cents: typical, spent, over_in, over_of: 12, order });
const same = (v: number) => MONTHS.map(() => v);
/** The last 12 months: the count is over the 12 complete months October 2025 to September 2026 (October 2025, not
 *  drawn, was under every target), so Eating out is over in 4 of 12, Shopping 5, Groceries 1 (December). */
export const TRENDS: SpendingTrends = {
  as_of: '2026-10-25', months: MONTHS, current: '2026-10',
  categories: [
    tr('dining', 'everyday', 'everyday', 50_000, null, 47_000, [41_000, 62_000, 38_000, 44_000, 47_000, 51_000, 45_500, 53_000, 48_000, 56_000, 49_000, 46_800], 4, 0),
    tr('shopping', 'everyday', 'everyday', 40_000, null, 39_000, [36_000, 98_000, 31_000, 29_000, 42_000, 38_000, 35_000, 43_000, 39_000, 41_000, 44_000, 51_200], 5, 1),
    tr('groceries', 'everyday', 'everyday', 130_000, null, 124_000, [118_000, 142_000, 121_000, 119_000, 126_000, 123_000, 129_000, 128_000, 124_000, 127_000, 122_000, 104_000], 1, 2),
    tr('personal', 'everyday', 'everyday', null, null, 9_000, [...same(9_000).slice(0, 11), 8_400], 0, 3),
    tr('utilities', 'fixed', 'fixed', null, 41_000, 41_000, [43_000, 52_000, 56_000, 54_000, 47_000, 40_000, 36_000, 38_000, 41_000, 44_000, 41_000, 39_500], 0, 4),
    tr('housing', 'fixed', 'steady', null, 268_000, 268_000, same(268_000), 0, 5),
    tr('insurance', 'fixed', 'steady', null, 36_000, 36_000, same(36_000), 0, 6),
    tr('giving', 'fixed', 'steady', null, 20_000, 20_000, same(20_000), 0, 7),
    tr('taxes', 'occasional', 'occasional', null, null, 0, [0, 0, 610_000, 0, 0, 0, 0, 0, 0, 0, 0, 0], 0, 8),
  ],
};
/** The last 6 months: the count is over April to September 2026, so Eating out and Shopping are over in 3 of 6. */
const OVER_IN_6: Record<string, number> = { dining: 3, shopping: 3 };
export const TRENDS6: SpendingTrends = {
  ...TRENDS, months: MONTHS.slice(6),
  categories: TRENDS.categories.map((r) => ({ ...r, spent: r.spent.slice(6), over_in: OVER_IN_6[r.category] ?? 0, over_of: 6 })),
};

const tg = (category: string, kind: TargetRow['kind'], monthly: number | null, typical: number | null, low: number | null,
  high: number | null, order: number): TargetRow =>
  ({ category, kind, monthly_cents: monthly, typical_cents: typical, usual_cents: typical, suggested_cents: typical || null, low_cents: low, high_cents: high, order });
export const TARGETS: SpendingTargets = {
  as_of: '2026-10-25',
  categories: [
    tg('groceries', 'everyday', 130_000, 124_000, 118_000, 142_000, 0), tg('dining', 'everyday', 50_000, 47_000, 38_000, 62_000, 1),
    tg('transport', 'everyday', 45_000, 44_000, 42_000, 52_000, 2), tg('shopping', 'everyday', 40_000, 39_000, 29_000, 98_000, 3),
    tg('home', 'everyday', 30_000, 29_000, 18_000, 41_000, 4), tg('kids', 'everyday', 25_000, 23_000, 19_000, 38_000, 5),
    tg('health', 'everyday', 20_000, 18_000, 9_500, 21_000, 6), tg('entertainment', 'everyday', 15_000, 12_000, 8_500, 16_000, 7),
    tg('personal', 'everyday', null, 9_000, 9_000, 9_000, 8), tg('gifts', 'everyday', null, 6_000, 0, 15_000, 9),
    tg('travel', 'everyday', null, 0, 0, 90_000, 10), tg('fees', 'everyday', null, 0, 0, 1_200, 11),
    tg('business_expense', 'everyday', null, 0, 0, 0, 12),
    tg('housing', 'fixed', null, 268_000, 268_000, 268_000, 13), tg('childcare_education', 'commitment', null, 82_000, 82_000, 82_000, 14),
    tg('utilities', 'fixed', null, 41_000, 36_000, 56_000, 15), tg('insurance', 'fixed', null, 36_000, 36_000, 36_000, 16),
    tg('giving', 'commitment', null, 20_000, 20_000, 20_000, 17), tg('subscriptions', 'fixed', null, 12_000, 11_600, 12_000, 18),
    tg('taxes', 'occasional', null, 0, 0, 610_000, 19),
  ],
  kept: [],
  updated_at: '2026-09-30T18:00:00+00:00', updated_by: 'Alex', has_targets: true, typical_income_cents: 1_020_000,
};
export const TARGETS_FIRST: SpendingTargets = {
  ...TARGETS, has_targets: false, updated_at: null, updated_by: null,
  categories: TARGETS.categories.map((r) => ({ ...r, monthly_cents: null })),
};
