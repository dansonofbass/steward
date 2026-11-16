import type { QueryClient } from '@tanstack/react-query';
import { api, json, patch } from './client';
import type { Payer, RuleMarkReply, SettleReply, TripBody, TripMarkReply, TripSummary } from './types';

/** Reimbursable spec: made on first use; the same name again is the payer already there. */
export const addPayer = (name: string) => api<Payer>('/api/reimburse/payers', json({ name }));
/** "Always reimbursable for …": the row and the untouched matching rows. */
export const addReimburseRule = (transaction_id: number, reimburser_id?: number) =>
  api<RuleMarkReply>('/api/reimburse/rules', json(reimburser_id === undefined ? { transaction_id } : { transaction_id, reimburser_id }));
export const addTrip = (body: TripBody) => api<{ trip: TripSummary }>('/api/reimburse/trips', json(body));
export const editTrip = (id: number, body: TripBody) => api<{ trip: TripSummary }>(`/api/reimburse/trips/${id}`, patch(body));
export const markTrip = (id: number, ids: number[]) => api<TripMarkReply>(`/api/reimburse/trips/${id}/mark`, json({ ids }));
export const settle = (id: number, amount_cents: number, category: string) =>
  api<SettleReply>(`/api/reimburse/payers/${id}/settle`, json({ amount_cents, category }));

/** Everything a mark, a repayment or a settle can change. */
export const invalidateReimburse = (qc: QueryClient) =>
  Promise.all(['reimburse', 'spending', 'transactions', 'review', 'plan'].map((k) => qc.invalidateQueries({ queryKey: [k] })));
