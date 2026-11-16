import { useQuery } from '@tanstack/react-query';
import { api, put } from '../../api/client';

export type Unavailable = { available: false; reason: string };
export type DueStatus = 'nothing' | 'paid' | 'short' | 'upcoming';
export type DueOut = { due: string; due_label: string; installment_cents: number; by_then_cents: number; paid_cents: number; still_due_cents: number; status: DueStatus };
export type AgencyOut = {
  agency: 'federal' | 'state'; label: string; method: 'current_year' | 'prior_year' | 'none_needed'; line: string;
  withholding_line: string | null; skip_line: string | null; current_tax_cents: number; current_required_cents: number;
  prior_required_cents: number | null; required_cents: number; withholding_cents: number; balance_cents: number; paid_cents: number; dues: DueOut[];
};
export type PaymentOut = { id: number; posted_at: string; posted_label: string; agency: 'federal' | 'state'; label: string; amount_cents: number; counts: boolean; description: string };
export type ReturnOut = { federal_tax_cents: number | null; federal_agi_cents: number | null; state_tax_cents: number | null; state_agi_cents: number | null };
export type WithholdingIn = { federal_ytd_cents: number; state_ytd_cents: number; as_of: string };
export type WithholdingOut = WithholdingIn & { as_of_label: string };
export type QuarterlyOut = {
  available: true; year: number; prior_year: number; state: string; state_name: string; rules_note: string; never: string;
  profit: { low_cents: number; high_cents: number; entered: boolean } | null; low_tax_cents: number | null; agencies: AgencyOut[];
  next: { due: string; due_label: string; federal_cents: number; state_cents: number } | null; notice: string | null;
  payments: PaymentOut[]; prior: ReturnOut | null; withholding: WithholdingOut | null; has_wages: boolean; needs_withholding: boolean;
  notes: string[]; email_on: boolean;
};
export type PointLabel = 'so_far' | 'low' | 'high' | 'full_year';
export type PlanPointOut = {
  label: PointLabel; label_text: string; profit_cents: number; net_earnings_cents: number; line: string;
  solo: { own_cents: number; business_cents: number; catch_up_cents: number; total_cents: number; saves_cents: number };
  sep: { total_cents: number; saves_cents: number };
};
export type PlansOut = {
  available: true; year: number; rules_note: string; never: string; default_point: PointLabel; w2_deferrals_cents: number;
  notes: string[]; points: PlanPointOut[]; deadlines: { solo: string[]; sep: string[] };
};
export type RothOut = {
  available: true; year: number; rate_now: number; rate_later: number | null; lean: 'roth' | 'traditional' | 'either'; line: string;
  later_line: string | null; conversion: { amount_cents: number; tax_cents: number; line: string } | null; rules_note: string;
  notes: string[]; never: string;
};

function getter<T>(path: string) {
  return () => api<T | Unavailable>(path);
}

export const QUARTERLY_KEY = ['taxes', 'quarterly'];
export const useQuarterly = () => useQuery({ queryKey: QUARTERLY_KEY, queryFn: getter<QuarterlyOut>('/api/taxes/quarterly') });
export const usePlans = () => useQuery({ queryKey: ['taxes', 'plans'], queryFn: getter<PlansOut>('/api/taxes/plans') });
export const useRoth = () => useQuery({ queryKey: ['taxes', 'roth'], queryFn: getter<RothOut>('/api/taxes/roth') });
export const saveReturn = (year: number, body: ReturnOut) => api<QuarterlyOut>(`/api/taxes/return/${year}`, put(body));
export const saveWithholding = (year: number, body: WithholdingIn) => api<QuarterlyOut>(`/api/taxes/withholding/${year}`, put(body));
export const markPayment = (id: number, counts: boolean) => api<QuarterlyOut>(`/api/taxes/payments/${id}`, put({ counts }));
export const setEmail = (on: boolean) => api<{ on: boolean }>('/api/taxes/email', put({ on }));
export const pct = (rate: number) => `${Math.round(rate * 100)}%`;
