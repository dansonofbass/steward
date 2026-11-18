import { useInfiniteQuery, useQuery, type QueryClient } from '@tanstack/react-query';
import { api } from './client';
import type {
  AccountList, EventList, Facts, FlagCount, History, InstitutionList, MemberList, Me, PasskeyList, ReviewQueue,
  CategoryRuleList, NoteList, PayerList, Reimbursements, TripDetail, SessionList, SetAsideDetail, SetAsideList, SimplefinStatus, SpendingFlow, SpendingMonth, SpendingTargets, SpendingTrends, Summary, TxnPage, UserList, BusinessReport, LineDetail,
} from './types';

export const useMe = () => useQuery({ queryKey: ['me'], queryFn: () => api<Me>('/api/auth/me'), retry: false, staleTime: 60_000 });

/** /me asked after a change to who is in which book (a book made, joined or restored), before opening it: BookScope sends
 *  an address it cannot find in /me to another book (F8). A /me already on its way was asked before the change, and
 *  fetchQuery would join that request and answer with the old list, so it is dropped first. */
export async function freshMe(qc: QueryClient): Promise<Me> {
  await qc.cancelQueries({ queryKey: ['me'] });
  return qc.fetchQuery({ queryKey: ['me'], queryFn: () => api<Me>('/api/auth/me'), staleTime: 0 });
}
export const useSummary = () => useQuery({ queryKey: ['summary'], queryFn: () => api<Summary>('/api/summary') });
export const useHistory = (days: number) =>
  useQuery({ queryKey: ['history', days], queryFn: () => api<History>(`/api/summary/history?days=${days}`) });
export const useAccounts = () => useQuery({ queryKey: ['accounts'], queryFn: () => api<AccountList>('/api/accounts') });

export type TxnParams = { q?: string; account_id?: number; category?: string; owner?: string; business?: boolean; sorted?: 'steward' | 'unsure'; from?: string; to?: string; batch?: number };
export function useTransactions(params: TxnParams) {
  return useInfiniteQuery({
    queryKey: ['transactions', params],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const qs = new URLSearchParams();
      Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== '' && v !== null) qs.set(k, String(v)); });
      qs.set('limit', '50');
      if (pageParam) qs.set('cursor', pageParam);
      return api<TxnPage>(`/api/transactions?${qs}`);
    },
    getNextPageParam: (last) => last.next_cursor,
  });
}

/** A transaction's notes (phase 12 decision 18). Shown on the detail only; never part of a list's key. */
export const useNotes = (id: number) =>
  useQuery({ queryKey: ['notes', id], queryFn: () => api<NoteList>(`/api/transactions/${id}/notes`) });

// The shell's badge reads this on every screen; Review invalidates it after each action, so a minute is safe.
export const useReview = (enabled = true) =>
  useQuery({ queryKey: ['review'], queryFn: () => api<ReviewQueue>('/api/review'), staleTime: 60_000, enabled });
export const useInstitutions = () => useQuery({ queryKey: ['institutions'], queryFn: () => api<InstitutionList>('/api/institutions') });
export const useEvents = (unresolved: boolean) =>
  useQuery({ queryKey: ['events', unresolved], queryFn: () => api<EventList>(`/api/events?unresolved=${unresolved}`) });
export const useSimplefin = () => useQuery({ queryKey: ['simplefin'], queryFn: () => api<SimplefinStatus>('/api/simplefin') });
export const usePasskeys = () => useQuery({ queryKey: ['passkeys'], queryFn: () => api<PasskeyList>('/api/auth/passkeys') });
export const useSessions = () => useQuery({ queryKey: ['sessions'], queryFn: () => api<SessionList>('/api/auth/sessions') });
export const useUsers = () => useQuery({ queryKey: ['users'], queryFn: () => api<UserList>('/api/users') });
export const useFacts = () => useQuery({ queryKey: ['facts'], queryFn: () => api<Facts>('/api/facts') });

/** Home's strip: Spending's money out and income for each of the last `months` months. Keyed under 'spending', so
 *  whatever refreshes Spending refreshes the strip. */
export const useSpendingFlow = (months = 12, enabled = true) =>
  useQuery({ queryKey: ['spending', 'flow', months], queryFn: () => api<SpendingFlow>(`/api/spending/flow?months=${months}`), enabled });

/** GET /api/plan, shared by Home's plan line and the Plan tab (one cache entry). A 503 is not retried. */
export function usePlanQuery<T>(enabled = true) {
  return useQuery({ queryKey: ['plan'], queryFn: () => api<T>('/api/plan'), enabled, retry: false });
}

export const useMembers = (slug: string) =>
  useQuery({ queryKey: ['members', slug], queryFn: () => api<MemberList>(`/api/books/${encodeURIComponent(slug)}/members`) });

// Home's tab count in a parent book (decision 5). Flag actions invalidate ['flags'], so a minute is safe.
export const useFlagCount = (enabled = true) =>
  useQuery({ queryKey: ['flags', 'count'], queryFn: () => api<FlagCount>('/api/flags/count'), staleTime: 60_000, enabled });

/** The Business page and Home's line (business plan). Tagging and rules invalidate ['business']. With no year the
 *  server answers for the household's this year, never the browser's (final review M6). */
export const useBusiness = (year: number | null, enabled = true) =>
  useQuery({
    queryKey: ['business', year ?? 'now'],
    queryFn: () => api<BusinessReport>(year === null ? '/api/business' : `/api/business?year=${year}`),
    enabled,
  });
export type TaxNotice = { notice: { due: string; line: string; federal_cents: number; state_cents: number } | null };
/** The quarterly taxes line on Home (tax decisions ruling 10): fetched only once Home is ready, household books only. */
export const useTaxNotice = (enabled = true) =>
  useQuery({ queryKey: ['taxes', 'notice'], queryFn: () => api<TaxNotice>('/api/taxes/notice'), enabled });
export const useBusinessLine = (year: number, line: string | null) =>
  useQuery({ queryKey: ['business', year, 'line', line], queryFn: () => api<LineDetail>(`/api/business/lines/${line}?year=${year}`), enabled: line !== null });

/** Spending's month (phase 11b). With no month the server answers for the household's this month, never the browser's. */
export const useSpending = (month: string | null, enabled = true) =>
  useQuery({
    queryKey: ['spending', month ?? 'now'],
    queryFn: () => api<SpendingMonth>(month ? `/api/spending?month=${encodeURIComponent(month)}` : '/api/spending'),
    enabled,
  });
export const useSpendingTrends = (months: 6 | 12, enabled = true) =>
  useQuery({ queryKey: ['spending', 'trends', months], queryFn: () => api<SpendingTrends>(`/api/spending/trends?months=${months}`), enabled });
export const useSpendingTargets = () =>
  useQuery({ queryKey: ['spending', 'targets'], queryFn: () => api<SpendingTargets>('/api/spending/targets') });

/** Setting aside (phase 11c): the list with its suggestions, and one set-aside. Every write invalidates ['setasides']. */
export const useSetAsides = (enabled = true) =>
  useQuery({ queryKey: ['setasides'], queryFn: () => api<SetAsideList>('/api/setasides'), enabled });
/** Settings, Category rules (phase 12): the household's rules, most rows first. Every write invalidates ['category-rules']. */
export const useCategoryRules = () =>
  useQuery({ queryKey: ['category-rules'], queryFn: () => api<CategoryRuleList>('/api/categorize/rules') });
/** Sorting redesign, Usual categories everywhere: the category menu's "Your usual", ranked as Review's chips are. */
export const useUsual = () =>
  useQuery({ queryKey: ['usual'], queryFn: () => api<{ keys: string[] }>('/api/categorize/usual'), staleTime: 300_000 });
/** Sorting redesign: the detail's "Also apply to N matching transactions", fetched once the category changes. */
export const useMatching = (id: number, enabled: boolean) =>
  useQuery({ queryKey: ['matching', id], queryFn: () => api<{ count: number }>(`/api/transactions/${id}/matching`), enabled });
export const useSetAside = (id: number) =>
  useQuery({ queryKey: ['setasides', id], queryFn: () => api<SetAsideDetail>(`/api/setasides/${id}`) });

/** Reimbursable spec: the payers, for the switch and its chooser. Every reimbursable write invalidates ['reimburse']. */
export const usePayers = (enabled = true) =>
  useQuery({ queryKey: ['reimburse', 'payers'], queryFn: () => api<PayerList>('/api/reimburse/payers'), staleTime: 300_000, enabled });
/** The Reimbursements tab: each payer's balance, the trips and the single charges. */
export const useReimbursements = () =>
  useQuery({ queryKey: ['reimburse', 'summary'], queryFn: () => api<Reimbursements>('/api/reimburse') });
/** A trip and its review list. */
export const useTrip = (id: number) =>
  useQuery({ queryKey: ['reimburse', 'trip', id], queryFn: () => api<TripDetail>(`/api/reimburse/trips/${id}`) });
