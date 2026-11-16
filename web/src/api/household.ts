// Shapes and hooks for household inputs that both the Plan tab and Set up Steward read
// (src/steward/api/{plan,children,ss}.py). Eager, so neither lazy chunk imports the other.
import { useQuery, type QueryClient } from '@tanstack/react-query';
import { api } from './client';

export type PlanLevel = 'two_year' | 'in_state_public' | 'out_of_state_public' | 'private';
export type CostLevel = PlanLevel | 'not_sure';
export type Names = { jr: string; spouse: string; joint: string };
export type Outlook = { years: number; total_cents: number; covered_cents: number };
export type Child = {
  id: number; label: string; birth_year: number; cost_level: CostLevel; account_id: number | null; monthly_contribution_cents: number;
  share_pct: number; covers_living: boolean; college_start_year: number; outlook: Outlook;
  plan529: { balance_cents: number; monthly_cents: number; real_return: number } | null;
};
export type ChildInput = Partial<Pick<Child, 'label' | 'birth_year' | 'cost_level' | 'account_id' | 'monthly_contribution_cents' | 'share_pct' | 'covers_living'>> & { set_type?: boolean };
export type PlanRow = { account_id: number; name: string; balance_cents: number; connected: boolean; deposits_monthly_cents: number | null; real_return: number };
export type Suggestion = { child_id: number; account_id: number; account_name: string; account_type: string };
export type CollegeLevelRow = { years: number; tuition_fees_cents: number; living_cents: number };
export type KidsList = { children: Child[]; college: { growth: number; levels: Record<PlanLevel, CollegeLevelRow> }; suggestions: Suggestion[]; plans: PlanRow[] };
export type Person = 'jr' | 'spouse';
export type EarningsRecord = { years: number; first_year: number; last_year: number; imported_at: string | null };
export type EarningsSummary = { records: Record<Person, EarningsRecord | null> };
export type SetupKey = 'household' | 'pay' | 'earnings' | 'earnings_spouse' | 'children' | 'mortgage' | 'health' | 'history';
export type SetupItem = { key: SetupKey; title: string; done: boolean; required: boolean; detail: string; suggested_cents: number | null };
export type SetupList = { ready: boolean; setup: SetupItem[]; names: Names };

export const usePlanSetup = () => useQuery({ queryKey: ['plan-setup'], queryFn: () => api<SetupList>('/api/plan/setup') });
export const useChildren = () => useQuery({ queryKey: ['children'], queryFn: () => api<KidsList>('/api/children') });
export const useEarnings = () => useQuery({ queryKey: ['ss'], queryFn: () => api<EarningsSummary>('/api/ss') });

/** After any input changes: the plan, setup lists, Next dollar and every input list refetch. */
export async function invalidatePlan(qc: QueryClient): Promise<void> {
  await Promise.all(['plan', 'plan-setup', 'next-dollar', 'facts', 'children', 'ss', 'plan-history', 'setup']
    .map((k) => qc.invalidateQueries({ queryKey: [k] })));
}
