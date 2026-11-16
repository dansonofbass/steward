// Test data only: the mockups' household (web/mockups/setasides.js), as the API would answer. Nothing in the app imports it.
import type { SetAsideDetail, SetAsideList, SetAsideRow, SetAsideSuggestion, SpendingSetAside } from '../../../api/types';

const HOUSE = { id: 21, name: 'House fund', balance_cents: 410_000, as_of: '2026-10-24', stale: false, shared_with: ['Water heater', 'Roof'] };
const KIDS = { id: 22, name: 'Kids fund', balance_cents: 60_000, as_of: '2026-10-24', stale: false, shared_with: [] as string[] };
const base: Omit<SetAsideRow, 'id' | 'name' | 'kind' | 'amount_cents' | 'monthly_cents' | 'yearly_cents' | 'installment_cents' | 'state'> = {
  due_month: null, due_day: null, second_month: null, second_day: null, due_year: null, first_month: '2026-11-01', next_due: null, days_until: null,
  missed_due: null, is_estimate: false, estimate: null, account: null, put_away_cents: 0, should_cents: 0, short_cents: 0, behind_cents: 0,
  counted_from: null, payee_key: null, payee_name: null, category: null, notes: null, paid: null, archived_at: null,
};
export const PROPTAX: SetAsideRow = {
  ...base, id: 1, name: 'Property tax', kind: 'twice_yearly', amount_cents: 421_000, monthly_cents: 70_200, yearly_cents: 842_000, installment_cents: 421_000,
  due_month: 11, due_day: 1, second_month: 4, second_day: 10, next_due: '2026-11-01', days_until: 7, account: HOUSE, put_away_cents: 410_000,
  should_cents: 421_200, state: 'short', short_cents: 11_000, counted_from: '2026-04-01', payee_key: 'COUNTY TAX COLLECTOR', payee_name: 'County Tax Collector', category: 'taxes',
};
export const HOLIDAYS: SetAsideRow = { ...base, id: 2, name: 'Holidays', kind: 'yearly', amount_cents: 150_000, monthly_cents: 12_500, yearly_cents: 150_000, installment_cents: 150_000, due_month: 12, due_day: 1, next_due: '2026-12-01', days_until: 37, state: 'no_account' };
export const CARREG: SetAsideRow = { ...base, id: 3, name: 'Car registration', kind: 'yearly', amount_cents: 41_200, monthly_cents: 3_400, yearly_cents: 41_200, installment_cents: 41_200, due_month: 3, due_day: 1, next_due: '2027-03-01', days_until: 127, state: 'no_account' };
export const CAMPS: SetAsideRow = {
  ...base, id: 4, name: 'Summer camps', kind: 'yearly', amount_cents: 240_000, monthly_cents: 20_000, yearly_cents: 240_000, installment_cents: 240_000, due_month: 6, due_day: 1,
  next_due: '2027-06-01', days_until: 219, account: KIDS, put_away_cents: 60_000, should_cents: 80_000, state: 'behind', behind_cents: 20_000, counted_from: '2026-06-01',
};
export const CARINS: SetAsideRow = { ...base, id: 5, name: 'Car insurance', kind: 'yearly', amount_cents: 186_000, monthly_cents: 15_500, yearly_cents: 186_000, installment_cents: 186_000, due_month: 8, due_day: 14, next_due: '2027-08-14', days_until: 293, state: 'no_account', payee_key: 'SAFEGUARD INSURANCE', payee_name: 'Safeguard Insurance', category: 'insurance' };
const HEATER_EST = { item: 'water_heater', installed_year: 2014, model_year: null, miles: null, lifespan: [10, 15] as [number, number], cost_range: [150_000, 300_000] as [number, number], planned_year: 2028, replacement_cents: 220_000, sale_cents: 0, confirmed: false, to_check: false, cost_to_check: true };
export const HEATER: SetAsideRow = {
  ...base, id: 6, name: 'Water heater', kind: 'one_off', amount_cents: 220_000, monthly_cents: 8_500, yearly_cents: 0, installment_cents: 220_000, due_year: 2028, due_month: 12,
  next_due: '2028-12-01', days_until: 768, is_estimate: true, estimate: HEATER_EST, account: { ...HOUSE, shared_with: ['Property tax', 'Roof'] }, state: 'on_track',
};
export const ROOF: SetAsideRow = {
  ...base, id: 7, name: 'Roof', kind: 'one_off', amount_cents: 1_800_000, monthly_cents: 24_300, yearly_cents: 0, installment_cents: 1_800_000, due_year: 2032, due_month: 12,
  next_due: '2032-12-01', days_until: 2229, is_estimate: true, estimate: { ...HEATER_EST, item: 'roof', lifespan: [20, 30], cost_range: [1_000_000, 2_600_000], planned_year: 2032, replacement_cents: 1_800_000 },
  account: { ...HOUSE, shared_with: ['Property tax', 'Water heater'] }, state: 'on_track',
};
export const SUGGESTIONS: SetAsideSuggestion[] = [
  { key: 'STATE FARM|insurance', name: 'Home insurance', group: 'home', kind: 'yearly', amount_cents: 180_000, yearly_cents: 180_000,
    monthly_cents: 15_000, months: [7], payee_key: 'STATE FARM', category: 'insurance', due_month: 7, due_day: 1, second_month: null,
    second_day: null, payments: ['2026-07-01', '2025-07-01'] },
  { key: 'ST OF CA DMV INTERNET|transport', name: 'DMV registration', group: 'car', kind: 'yearly', amount_cents: 41_200,
    yearly_cents: 41_200, monthly_cents: 3_433, months: [3], payee_key: 'ST OF CA DMV INTERNET', category: 'transport', due_month: 3,
    due_day: 10, second_month: null, second_day: null, payments: ['2026-03-10', '2025-03-03'] },
  { key: 'MAPLE COURT HOA|housing', name: 'Maple Court HOA', group: 'other', kind: 'twice_yearly', amount_cents: 45_000,
    yearly_cents: 90_000, monthly_cents: 7_500, months: [1, 7], payee_key: 'MAPLE COURT HOA', category: 'housing', due_month: 7,
    due_day: 15, second_month: 1, second_day: 15, payments: ['2026-07-15', '2026-01-15', '2025-07-15', '2025-01-15'] },
];
export const LIST: SetAsideList = {
  as_of: '2026-10-25', monthly_cents: 154_400, count: 7, yearly_cents: 1_459_200, one_off_cents: 2_020_000, needs_look: 2,
  rows: [PROPTAX, HOLIDAYS, CARREG, CAMPS, CARINS, HEATER, ROOF], suggestions: SUGGESTIONS, dismissed: [], history_months: 25, first_visit: false,
};
export const FIRST: SetAsideList = { ...LIST, monthly_cents: 0, count: 0, yearly_cents: 0, one_off_cents: 0, needs_look: 0, rows: [], first_visit: true };
export const YOUNG: SetAsideList = { ...FIRST, suggestions: [], history_months: 3 };
export const PROPTAX_DETAIL: SetAsideDetail = {
  ...PROPTAX, as_of: '2026-10-25', find_from: null, find_to: null,
  dues: [{ due_on: '2026-11-01', status: 'next', which: 'first', amount_cents: 421_000, paid_on: null, days_late: null, days_until: 7 },
    { due_on: '2027-04-10', status: 'upcoming', which: 'second', amount_cents: 421_000, paid_on: null, days_late: null, days_until: 167 }],
  payments: [
    { transaction_id: 301, posted_at: '2026-04-10', account_name: 'Checking', merchant: 'County Tax Collector', raw_description: 'COUNTY TAX COLLECTOR', category: 'taxes', amount_cents: -421_000, due_on: '2026-04-10', how: 'auto', late: false, days_late: 0 },
    { transaction_id: 302, posted_at: '2025-11-03', account_name: 'Checking', merchant: 'County Tax Collector', raw_description: 'COUNTY TAX COLLECTOR', category: 'taxes', amount_cents: -421_000, due_on: '2025-11-01', how: 'auto', late: true, days_late: 2 },
    { transaction_id: 303, posted_at: '2025-04-09', account_name: 'Checking', merchant: 'County Tax Collector', raw_description: 'COUNTY TAX COLLECTOR', category: 'taxes', amount_cents: -418_000, due_on: '2025-04-10', how: 'auto', late: false, days_late: 0 },
  ],
  replace: null, replace_offer: null,
};
export const HEATER_DETAIL: SetAsideDetail = { ...HEATER, as_of: '2026-10-25', find_from: null, find_to: null,
  estimate: { ...HEATER_EST, age: 12, sources: ['Typical water heater lifespan', 'Typical water heater cost'] }, dues: [{ due_on: '2028-12-01', status: 'next', which: null, amount_cents: 220_000, paid_on: null, days_late: null, days_until: 768 }], payments: [], replace: null, replace_offer: null };
const HEATER_NEXT = { item: 'water_heater', label: 'Water heater', installed_year: 2028, model_year: null, miles: null, age: 0, miles_per_year: null, lifespan: [10, 15] as [number, number], lifespan_miles: null, range: [2038, 2043] as [number, number], decided_by: 'age' as const, planned_year: 2042, due_year: 2042, due_month: 12, cost_range: [150_000, 300_000] as [number, number], replacement_cents: 235_000, sale_cents: 0, amount_cents: 235_000, months: 177, first_month: '2028-04-01', monthly_cents: 1_328, sources: ['Typical water heater lifespan', 'Typical water heater cost'], to_check: false, cost_to_check: true };
export const HEATER_PAID: SetAsideDetail = {
  ...HEATER_DETAIL, next_due: null, days_until: null, paid: { transaction_id: 404, posted_at: '2028-03-14', cents: 235_000, account_name: 'House fund' },
  dues: [{ due_on: '2028-12-01', status: 'paid', which: null, amount_cents: 220_000, paid_on: '2028-03-14', days_late: 0, days_until: 0 }],
  payments: [{ transaction_id: 404, posted_at: '2028-03-14', account_name: 'House fund', merchant: "Dale's Plumbing", raw_description: 'DALES PLUMBING', category: 'home', amount_cents: -235_000, due_on: '2028-12-01', how: 'hand', late: false, days_late: 0 }],
  replace: { paid_on: '2028-03-14', paid_cents: 235_000, next: HEATER_NEXT },
  replace_offer: { year: 2042, cents: 235_000, monthly_cents: 1_328 },
};
export const OCT_SECTION: SpendingSetAside = {
  monthly_cents: 154_400, count: 7, yearly_cents: 1_459_200, one_off_cents: 2_020_000, names: ['Property tax', 'Holidays', 'Car registration'],
  needs_look: [PROPTAX, CAMPS], paid: [], next: { name: 'Property tax', next_due: '2026-11-01' },
};
export const NOV_SECTION: SpendingSetAside = {
  ...OCT_SECTION, needs_look: [CAMPS], next: { name: 'Holidays', next_due: '2026-12-01' },
  paid: [{ set_aside_id: 1, name: 'Property tax', transaction_id: 305, payee: 'County Tax Collector', posted_at: '2026-11-01', cents: 421_000, late: false, account_name: 'Checking', category: 'taxes', archived: false }],
};
