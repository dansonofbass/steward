// Calls only Profile makes. Every write answers with an Undo token (P26); a rename has none (P32).
import { useQuery } from '@tanstack/react-query';
import { api, del, json, patch, put } from '../../api/client';
import type { Child, ChildInput, Person } from '../../api/household';
import type { Account } from '../../api/types';

export const savedNote = (name: string) => `Saved by ${name}`;

/** POST /api/facts: one dated fact (facts keep their history). Resolves with the Undo token. */
export async function saveFact(key: string, value: string, note: string | null = null): Promise<string | null> {
  const r = await api<{ undo: string | null }>('/api/facts', json({ key, value, note }));
  return r.undo;
}

type WithUndo<T> = T & { undo: string | null };
export const addChild = (c: ChildInput) => api<WithUndo<Child>>('/api/children', json(c));
export const changeChild = (id: number, c: ChildInput) => api<WithUndo<Child>>(`/api/children/${id}`, patch(c));
export const removeChild = (id: number) => api<{ undo: string | null }>(`/api/children/${id}`, del());


export type Detected = { posted_at: string; amount_cents: number; varied: { lo: number; hi: number } | null };
export type Loan = { account_id: number; name: string; balance_cents: number | null; as_of: string | null; manual: boolean;
  institution: string; rate_bp: number | null; payment_cents?: number | null; payoff_date?: string | null; detected?: Detected | null };
export type Thing = { account_id: number; name: string; value_cents: number | null; as_of: string | null };
export type HomeData = { owns_home: boolean | null; where_you_live: number | null;
  properties: (Thing & { mortgage: Loan | null })[]; cars: (Thing & { loan: Loan | null })[]; loans: Loan[]; mortgages: Loan[] };
type AccountReply = Account & { undo: string | null };

export const useProfileHome = () => useQuery({ queryKey: ['profile-home'], queryFn: () => api<HomeData>('/api/profile/home') });
export const addAccount = (body: { name: string; type: string; owner: string; balance_cents: number; loan_id?: number | null }) =>
  api<AccountReply>('/api/accounts', json(body));
export const patchAccount = (id: number, body: Record<string, unknown>) => api<AccountReply>(`/api/accounts/${id}`, patch(body));
export const setBalance = (id: number, cents: number) => api<AccountReply>(`/api/accounts/${id}/balance`, json({ balance_cents: cents }));
export const setWhere = (id: number) => api<HomeData & { undo: string | null }>('/api/profile/home/where', put({ account_id: id }));

export type BenefitPerson = { source: 'record' | 'estimate' | 'none'; years: number; first: number | null; last: number | null; at_67_cents: number | null };
export type Benefits = { jr: BenefitPerson; spouse: BenefitPerson;
  health: { premium_cents: number | null; suggested_cents: number; part_b_monthly_cents: number; rules_year: number } };
export const useProfileBenefits = () => useQuery({ queryKey: ['profile-benefits'], queryFn: () => api<Benefits>('/api/profile/benefits') });

export type FactRow = { value: string; as_of: string; note: string | null };
export type EarningsImport = { person: Person; years: number; first_year: number; last_year: number; skipped: number; undo?: string | null };
export const factHistory = (key: string) => api<{ history: FactRow[] }>(`/api/facts/${encodeURIComponent(key)}/history`);
/** M2-B ruling 0: the raw file with an XML type, whatever the browser calls it. */
export const uploadEarnings = (person: Person, file: Blob) =>
  api<EarningsImport>(`/api/ss/import?person=${person}`, { method: 'POST', body: file, headers: { 'Content-Type': 'application/xml' } });
