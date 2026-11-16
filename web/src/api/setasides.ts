import type { QueryClient } from '@tanstack/react-query';
import { api, del, json, put } from './client';
import type { EstimatePreview, PreviewIn, SetAsideBody, SetAsideDetail, SetAsideList } from './types';

export const addSetAside = (body: SetAsideBody) => api<SetAsideDetail>('/api/setasides', json(body));
/** The PUT is partial: send only the fields that changed. */
export const editSetAside = (id: number, body: Partial<SetAsideBody>) => api<SetAsideDetail>(`/api/setasides/${id}`, put(body));
export const stopSetAside = (id: number) => api<void>(`/api/setasides/${id}`, del());
export const replaceSetAside = (id: number) => api<SetAsideDetail>(`/api/setasides/${id}/replace`, json({}));
export const skipDue = (id: number, due_on: string) => api<SetAsideDetail>(`/api/setasides/${id}/skip`, json({ due_on }));
/** The server's own arithmetic for any draft (viewer_ok, but it takes a write lock: callers debounce 300-500 ms). */
export const estimateSetAside = (body: PreviewIn, signal?: AbortSignal) => api<EstimatePreview>('/api/setasides/estimate', { ...json(body), signal });
/** P26: the suggestions a person ticked, made in one write with one Undo (at most 50; any bad one refuses them all). */
export const addMany = (items: SetAsideBody[]) => api<{ ids: number[]; monthly_cents: number; undo: string }>('/api/setasides/many', json({ items }));
export const dismissSuggestion = (payee_key: string, category: string) => api<SetAsideList>('/api/setasides/suggestions/dismiss', json({ payee_key, category }));
export const restoreSuggestion = (payee_key: string, category: string) => api<SetAsideList>('/api/setasides/suggestions/restore', json({ payee_key, category }));
export const matchPayment = (transaction_id: number, set_aside_id: number) => api<SetAsideDetail>('/api/setasides/match', json({ transaction_id, set_aside_id }));
export const unmatchPayment = (transaction_id: number) => api<void>(`/api/setasides/match/${transaction_id}`, del());

/** After any set-aside write (engineering choice 15): Spending and Home's strip, the list, the Plan, Transactions and Home's summary. */
export async function invalidateSetAsides(qc: QueryClient): Promise<void> {
  await Promise.all(['spending', 'setasides', 'plan', 'transactions', 'summary'].map((k) => qc.invalidateQueries({ queryKey: [k] })));
}
