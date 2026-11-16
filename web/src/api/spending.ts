import { api, del, json, put } from './client';
import type { SpendingKind, SpendingTargets, TargetsBody } from './types';

/** PUT /api/spending/targets: only the changed rows. Answers with the saved targets. */
export const saveTargets = (body: TargetsBody) => api<SpendingTargets>('/api/spending/targets', put(body));
/** The category page's kind select (P12): saves at once and answers with its Undo. */
export const saveKind = (category: string, kind: SpendingKind) =>
  api<{ category: string; kind: SpendingKind; undo: string }>(`/api/spending/kinds/${encodeURIComponent(category)}`, put({ kind }));
/** Giving outside these accounts (P13): a monthly fact; 0 clears it. */
export const saveGivingOutside = (cents: number) =>
  api<{ undo: string }>('/api/facts', json({ key: 'giving.outside_cents', value: String(cents) }));

export type CheckReply = { target_cents: number; until: string | null; undo: string };
/** The monthly target check (P19): Set writes the typical month, Keep leaves the target for three months. */
export const answerCheck = (category: string, answer: 'set' | 'keep', target_cents: number) =>
  api<CheckReply>(`/api/spending/targets/${encodeURIComponent(category)}/check`, json({ answer, target_cents }));
/** Kept targets' Check again (P20). */
export const checkAgain = (category: string) =>
  api<{ undo: string }>(`/api/spending/targets/${encodeURIComponent(category)}/kept`, del());
