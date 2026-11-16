// Fictional figures for Margaret Ellis's Care screen, shaped like the vault's answer.
import type { CareCost, CareOut, CareScenario, CareYear, Monthly } from './api';

export const PARENT = {
  slug: 'margaret-ellis', name: 'Margaret Ellis', kind: 'parent' as const,
  owners: [{ key: 'margaret', label: 'Margaret' }, { key: 'robert-husband', label: 'Robert (husband)' }, { key: 'joint', label: 'Joint' }],
};
const LIMIT = 13_000_000;
const year = (y: number, balance: number, extra: Partial<CareYear> = {}): CareYear => ({
  year: y, age: y - 1944, balance_cents: balance, care_cents: 0, ltc_cents: 0, tax_cents: 0, short_cents: 0, home_sale_cents: 0,
  medi_cal: balance <= LIMIT ? 'eligible' : 'over_limit', medi_cal_over_cents: Math.max(balance - LIMIT, 0), ...extra,
});
const FIELDS = {
  start_year: null, hours_week: null, adult_day_days: null, room: null, sell_home_year: null, home_price_cents: null,
  home_basis_cents: null, selling_cost_bp: 600, family_monthly_cents: 0, spending_change_monthly_cents: 0,
};
const TYPICAL = 'Typical in California: CareScout Cost of Care Survey 2025, raised 4% a year to 2026.';

export const AT_HOME: CareScenario = {
  id: 1, level: 'at_home', ...FIELDS, label: 'At home as today', levers: [], care_monthly_cents: 0, cost_lines: [],
  headline: 'Money lasts until 2032 (age 88)', lasts_until: 2032, ltc_line: null, ltc_runs_out: null,
  medi_cal_line: 'Medi-Cal in 2026: Not yet: countable assets are $130,000 over the limit (2026 rules).',
  medi_cal_when: 'Meets the Medi-Cal limit in 2030 (age 86).', medi_cal_first_year: 2030,
  years: [year(2026, 26_000_000), year(2027, 22_000_000), year(2028, 18_000_000), year(2029, 14_000_000), year(2030, 10_000_000),
    year(2031, 6_000_000), year(2032, 2_000_000), year(2033, 0, { short_cents: 2_000_000 })],
};
export const ASSISTED: CareScenario = {
  id: 2, level: 'assisted_living', ...FIELDS, start_year: 2027, label: 'Assisted living from 2027', levers: [],
  care_monthly_cents: 728_000, cost_lines: [`Assisted living: $7,280 a month. ${TYPICAL}`], headline: 'Money lasts until 2028 (age 84)',
  lasts_until: 2028, ltc_line: 'Long-term care insurance pays from 2027 and runs out in 2030.', ltc_runs_out: 2030,
  medi_cal_line: 'Medi-Cal in 2027: Eligible after spending down $21,000 (2026 rules).',
  medi_cal_when: 'Meets the Medi-Cal limit in 2028 (age 84).', medi_cal_first_year: 2028,
  years: [year(2026, 26_000_000), year(2027, 15_100_000, { care_cents: 8_736_000, ltc_cents: 4_125_000, medi_cal: 'after_spend_down' }),
    year(2028, 9_600_000, { care_cents: 8_736_000, ltc_cents: 5_475_000 }), year(2029, 0, { care_cents: 8_736_000, short_cents: 1_000_000 })],
};
export const COSTS: CareCost[] = [
  { key: 'in_home_hourly', label: 'In-home help', per: 'hour', cents: 4160, text: '$41.60 an hour', line: TYPICAL, quote: null },
  { key: 'assisted_living_monthly', label: 'Assisted living', per: 'month', cents: 728_000, text: '$7,280 a month', line: TYPICAL, quote: null },
];
export const MONTHLY: Monthly = {
  months: [
    { month: '2026-09', in_cents: 352_500, out_cents: 120_000, net_cents: 232_500,
      categories: [{ category: 'groceries', in_cents: 0, out_cents: 80_000 }, { category: 'insurance', in_cents: 0, out_cents: 40_000 }] },
    { month: '2026-10', in_cents: 0, out_cents: 30_000, net_cents: -30_000, categories: [{ category: 'utilities', in_cents: 0, out_cents: 30_000 }] },
  ],
  expected: [{ on: '2026-10-16', label: 'Southern California Edison', cents: -9_000, source: 'known' },
    { on: '2026-11-03', label: 'Social Security', cents: 214_000, source: 'item' }],
  expected_in_cents: 214_000, expected_out_cents: 9_000, cash_cents: 50_000, floors_cents: 20_000, above_floor_cents: 30_000,
  short_line: null, short_cents: 0, undated_line: null,
};
export const CARE: CareOut = {
  this_year: 2026, set_up: true, max_scenarios: 5,
  people: [{ key: 'margaret', label: 'Margaret' }, { key: 'robert-husband', label: 'Robert (husband)' }],
  setup: { person: 'margaret', person_label: 'Margaret', birth_year: 1944, spouse_birth_year: null, state: 'CA', care_inflation_bp: 400, spending_monthly_cents: null },
  age: 82, home_value_cents: 78_000_000,
  spending: { monthly_cents: 400_000, months: 5, typed: false, line: 'Spending: $4,000 a month, from the last 5 months of transactions, taxes and transfers left out.' },
  scenarios: [AT_HOME, ASSISTED], costs: COSTS,
  medi_cal: {
    rule_line: 'Limit $130,000 for one person, from January 1, 2026 (2026 rules, DHCS All County Welfare Directors Letter 25-14).',
    url: 'https://www.dhcs.ca.gov/services/medi-cal/eligibility/letters/Documents/25-14.pdf',
    disclaimer: 'An estimate to take to an elder-law attorney, not legal advice.',
    topics: ['Estate recovery after a death', 'Protections for a spouse who stays at home', 'The 30-month look-back on gifts and transfers (2026 rules)'],
  },
  how: ['Spending: $4,000 a month, from the last 5 months of transactions, taxes and transfers left out.', 'Care costs rise 4% a year.'],
  notes: [], monthly: MONTHLY,
};
export const NOT_SET_UP: CareOut = {
  ...CARE, set_up: false, setup: null, age: null, home_value_cents: null, spending: null, scenarios: [], costs: [], medi_cal: null, how: [], notes: [],
};
