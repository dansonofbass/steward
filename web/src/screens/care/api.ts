// Care's API (src/steward/api/care.py). Money is cents; every write answers the whole screen.
import { useQuery } from '@tanstack/react-query';
import { api, del, json, patch, put } from '../../api/client';

export type Level = 'at_home' | 'in_home_help' | 'assisted_living' | 'memory_care' | 'nursing_home';
export type CostKey = 'in_home_hourly' | 'adult_day_daily' | 'assisted_living_monthly' | 'memory_care_monthly'
  | 'nursing_home_shared_monthly' | 'nursing_home_private_monthly';
export type MediCalStatus = 'eligible' | 'over_limit' | 'after_spend_down';
export type CareYear = {
  year: number; age: number; balance_cents: number; care_cents: number; ltc_cents: number; tax_cents: number;
  short_cents: number; home_sale_cents: number; medi_cal: MediCalStatus; medi_cal_over_cents: number;
};
export type ScenarioFields = {
  level: Level; start_year: number | null; hours_week: number | null; adult_day_days: number | null;
  room: 'shared' | 'private' | null; sell_home_year: number | null; home_price_cents: number | null;
  home_basis_cents: number | null; selling_cost_bp: number; family_monthly_cents: number; spending_change_monthly_cents: number;
};
export type CareScenario = ScenarioFields & {
  id: number; label: string; levers: string[]; care_monthly_cents: number; cost_lines: string[]; headline: string;
  lasts_until: number | null; ltc_line: string | null; ltc_runs_out: number | null; medi_cal_line: string;
  medi_cal_when: string; medi_cal_first_year: number | null; years: CareYear[];
};
export type CareCost = {
  key: CostKey; label: string; per: 'hour' | 'day' | 'month'; cents: number; text: string; line: string;
  quote: { cents: number; quoted_on: string } | null;
};
export type CareSetup = {
  person: string; person_label: string; birth_year: number; spouse_birth_year: number | null; state: string;
  care_inflation_bp: number; spending_monthly_cents: number | null;
};
export type Expected = { on: string; label: string; cents: number; source: 'item' | 'known' };
export type MonthRow = {
  month: string; in_cents: number; out_cents: number; net_cents: number;
  categories: { category: string; in_cents: number; out_cents: number }[];
};
export type Monthly = {
  months: MonthRow[]; expected: Expected[]; expected_in_cents: number; expected_out_cents: number; cash_cents: number;
  floors_cents: number; above_floor_cents: number; short_line: string | null; short_cents: number; undated_line: string | null;
};
export type CareOut = {
  this_year: number; set_up: boolean; max_scenarios: number; people: { key: string; label: string }[];
  setup: CareSetup | null; age: number | null; home_value_cents: number | null;
  spending: { monthly_cents: number; months: number; typed: boolean; line: string } | null;
  scenarios: CareScenario[]; costs: CareCost[];
  medi_cal: { rule_line: string; url: string | null; disclaimer: string; topics: string[] } | null;
  how: string[]; notes: string[]; monthly: Monthly;
};

export const careKey = ['care'];
export const useCare = () => useQuery({ queryKey: careKey, queryFn: () => api<CareOut>('/api/care') });
export const saveSetup = (body: Record<string, unknown>) => api<CareOut>('/api/care/setup', put(body));
export const addScenario = (body: ScenarioFields) => api<CareOut>('/api/care/scenarios', json(body));
export const editScenario = (id: number, body: ScenarioFields) => api<CareOut>(`/api/care/scenarios/${id}`, patch(body));
export const removeScenario = (id: number) => api<CareOut>(`/api/care/scenarios/${id}`, del());
export const saveQuote = (key: CostKey, body: { cents: number; quoted_on: string }) => api<CareOut>(`/api/care/quotes/${key}`, put(body));
export const removeQuote = (key: CostKey) => api<CareOut>(`/api/care/quotes/${key}`, del());
