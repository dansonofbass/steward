// The investment account page's data (investment views spec): GET /accounts/{id}/investment and GET /contributions.
// The shapes mirror services/investment_page.py and services/contributed.py.
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { AccountType } from '../../../api/types';

export type Sends = { holdings: boolean; transactions: boolean };
export type YearFigures = {
  start: string; from_jan1: boolean; start_cents: number; end_cents: number; change_cents: number; change_pct: number | null;
  put_in_cents: number; growth_cents: number; estimated: boolean;
};
export type SeriesPoint = { date: string; balance_cents: number; put_in_cents: number };
export type MixClass = 'us_stock' | 'intl_stock' | 'bond' | 'cash' | 'other';
export type HoldingRow = {
  id: number; symbol: string | null; name: string; value_cents: number; ratio_pct: string | null;
  ratio_from: 'override' | 'table' | 'stored' | null; cost_cents: number | null;
};
export type HoldingsOut = {
  as_of: string; source: 'feed' | 'import' | 'statement'; statement_month?: string | null; filename: string | null; rows: HoldingRow[]; total_cents: number;
  mix: { class: MixClass; cents: number }[]; unknown: number; known_cost_cents: number;
};
export type LimitLine = {
  kind: 'k401' | 'ira' | 'hsa'; owner: 'jr' | 'spouse' | 'household'; name: string; label: string; year: number;
  limit_cents: number | null; in_cents: number; on_pace_cents: number; short_cents: number; raise_pct: number | null;
  maxed: boolean; estimated: boolean;
};
export type Contributed = {
  you_cents: number; you_from: 'deposits' | 'payroll' | 'estimate' | 'none'; match_cents: number;
  match_from: 'deposits' | 'estimate' | 'none'; rollover_cents: number; out_cents: number;
};
export type InvestmentPage = {
  account_id: number; type: AccountType; institution: string; manual: boolean; sends: Sends | null;
  year: YearFigures | null; since: string | null; series: SeriesPoint[];
  holdings: HoldingsOut | null; advisory: { fee_bp: number; cost_cents: number } | null; all_in: { cents: number; pct: string } | null;
  contributions: { this_year: Contributed; line: LimitLine | null; missing: boolean } | null;
};
export type Limits = { year: number; missing: boolean; lines: LimitLine[] };

export const useInvestment = (id: number) =>
  useQuery({ queryKey: ['investment', id], queryFn: () => api<InvestmentPage>(`/api/accounts/${id}/investment`) });
export const useLimits = () => useQuery({ queryKey: ['contributions'], queryFn: () => api<Limits>('/api/contributions') });

/** After anything the page saves: its own data, the limits, and the accounts (an advisory fee is on the account). */
export function useRefreshInvestments(): () => Promise<unknown> {
  const qc = useQueryClient();
  return () => Promise.all(['investment', 'contributions', 'accounts'].map((k) => qc.invalidateQueries({ queryKey: [k] })));
}
