import type { QueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { UndoReply } from '../../api/types';

/** One open "Same account?" question (GET /same-accounts). For a pair already in the book, name, bank and balance are
 *  the newer account's, and candidate_* the older one's, which a merge keeps. */
export type Question = {
  id: string; kind: 'held' | 'in_book'; name: string; bank: string; balance_cents: number | null;
  candidate_id: number; candidate_name: string; candidate_bank: string; candidate_balance_cents: number | null;
  matches: number; same_balance: boolean; since: string;
};
export type Merged = { kept: { id: number; name: string }; dropped: number; kept_new: number };
export type MergeReply = { merged: Merged; undo: string };

const q = (id: string) => encodeURIComponent(id);
export const getQuestions = () => api<{ questions: Question[] }>('/api/same-accounts');
export const mergeQuestion = (id: string) => api<MergeReply>(`/api/same-accounts/${q(id)}/merge`, { method: 'POST' });
export const keepApart = (id: string) => api<{ undo: string }>(`/api/same-accounts/${q(id)}/different`, { method: 'POST' });
export const previewMerge = (id: number, into: number) => api<{ merged: Merged }>(`/api/accounts/${id}/merge-preview?into=${into}`);
export const mergeInto = (id: number, into: number) =>
  api<MergeReply>(`/api/accounts/${id}/merge-into`, { method: 'POST', body: JSON.stringify({ into }) });
export const undoIt = (token: string) => api<UndoReply>(`/api/undo/${q(token)}`, { method: 'POST' });

/** After an answer or its Undo, everything that counts accounts or their rows reads again. */
export const refresh = (qc: QueryClient) => Promise.all(
  ['same-accounts', 'accounts', 'summary', 'history', 'transactions', 'review'].map((k) => qc.invalidateQueries({ queryKey: [k] })));
