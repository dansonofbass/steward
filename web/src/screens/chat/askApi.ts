// The Ask page's reads and writes (src/steward/api/chat.py, plan B). Query keys are cached per book (queryClient.ts).
import { useQuery } from '@tanstack/react-query';
import { api, del, json } from '../../api/client';
import { cleanAbout, type AboutIn } from '../../ask/about';

export type { AboutIn };

export type Chip = { start: number; end: number; label: string; layer: string };
export type Preview = { text: string; as_written: boolean; chips: Chip[]; labels: Record<string, string> };
/** POST /chat/about's wire object (steward_boundary.protocol.ABOUT): aliases, enums, ISO days and months, numbers. */
export type AboutWire =
  | { kind: 'account'; account: string }
  | { kind: 'category'; category: string; month: string }
  | { kind: 'plan' }
  | { kind: 'transaction'; date: string; amount_cents: number; category: string; account: string }
  | { kind: 'flag'; check: string; date: string }
  | { kind: 'care'; scenario?: number; level?: string };
export type AboutReply = { about: AboutWire; sent: string; chips: Chip[]; labels: Record<string, string> };
export type Step = { tool: string; done: string };
export type Saw = { key: string; name: string; title: string; summary: string; is_error: boolean; payload: unknown };
export type TurnApproval = { state: 'approved' | 'declined' | 'viewer'; line: string; log_key: string | null };
export type Turn = {
  turn_id: string; asked: string; sent: string | null; chips: Chip[]; as_written: boolean; who: string; when: string;
  steps: Step[]; answer: string; stop: string | null; line: string | null; meta: string | null; saw: Saw[];
  approval: TurnApproval | null; looked_into: boolean; unfinished: boolean;
  /** Ask about this P9: what it was asked about, as sent. */
  about?: { chip: AboutWire; sent: string } | null;
};
export type Conversation = { id: number; title: string; ended: boolean; requests: number; long_line: string | null; labels: Record<string, string>; turns: Turn[] };
export type ConversationRow = { id: number; title: string; group: 'today' | 'week' | 'earlier'; when: string; questions: number; store_names: boolean; requests: number };
/** `store` is what goes; `full` is the recipient's name a tick sends instead (public issue #1), null when there is none. */
export type CardRow = { date: string; store: string; amount_cents: number; category: string; account: string; full?: string | null };
export type CardPayee = { payee: string; name: string; full?: string | null };
export type Card = {
  call_id: string; reason: string; count: number; first: string | null; last: string | null; names: { name: string; count: number }[];
  rows: CardRow[]; payees: CardPayee[]; accounts: { alias: string; label: string }[]; until: string; more: boolean;
  /** The card's hash (plan B Task 6.5); the approval must send it back or the server answers 404. */
  hash: string;
};
export type DoneEvent = {
  type: 'done'; stop: string; line: string | null; answer: string; long_line: string | null; conversation_id: number;
  turn_id: string; requests: number; cost_cents: number; parts: number; bytes: number; meta: string;
};
export type ApprovalEvent =
  | { type: 'approval'; state: 'ask'; card: Card }
  | { type: 'approval'; state: 'viewer'; managers: string[]; where: string }
  | { type: 'approval'; state: 'approved'; line: string; log_key: string | null }
  | { type: 'approval'; state: 'declined'; line: string };
export type AskEvent =
  | { type: 'conversation'; id: number; note: string | null; turn_id: string }
  | { type: 'labels'; labels: Record<string, string> }
  | { type: 'redacted'; text: string; chips: Chip[] }
  | { type: 'status'; tool: string; text: string; done: string }
  | { type: 'text'; delta: string }
  | ApprovalEvent
  | DoneEvent;

export const useConversations = () => useQuery({
  queryKey: ['chat', 'conversations'], queryFn: () => api<{ conversations: ConversationRow[] }>('/api/chat/conversations'),
});
export const useConversation = (id: number | null) => useQuery({
  queryKey: ['chat', 'conversation', id], enabled: id !== null,
  queryFn: () => api<Conversation>(`/api/chat/conversations/${id}`),
});
export const preview = (text: string, signal: AbortSignal) => api<Preview>('/api/chat/preview', { ...json({ text }), signal });
export const aboutPreview = (about: AboutIn, signal?: AbortSignal) =>
  api<AboutReply>('/api/chat/about', { ...json({ about: cleanAbout(about) }), signal });
export const prewarm = () => api<{ sent: boolean }>('/api/chat/prewarm', json({}));
export const markSeen = () => api<{ seen: true }>('/api/chat/seen', json({}));
/** `ticked`: the rows ("r0") and payees ("p0") whose recipient's name goes too. */
export const answerCard = (turnId: string, callId: string, send: boolean, hash: string, ticked: string[] = []) =>
  api<{ ok: true }>('/api/chat/approvals', json({ turn_id: turnId, call_id: callId, send, hash, ticked }));
export const stopTurn = (turnId: string) => api<{ ok: true }>(`/api/chat/turns/${encodeURIComponent(turnId)}/stop`, json({}));
export const deleteConversation = (id: number) => api<{ deleted: true }>(`/api/chat/conversations/${id}`, del());

/** A part the gateway's model check removed (a guess), as opposed to one Steward replaced from the book (exact). */
export const isModelChip = (c: Chip) => c.layer === 'gliner' || c.layer === 'presidio';
export const fill = (template: string, vars: Record<string, string | number>) =>
  template.replace(/\{(\w+)\}/g, (_, k: string) => String(vars[k] ?? ''));
const list = (names: string[], word: string) =>
  names.length <= 1 ? names.join('') : `${names.slice(0, -1).join(', ')} ${word} ${names[names.length - 1]}`;
export const andList = (names: string[]) => list(names, 'and');
export const orList = (names: string[]) => list(names, 'or');
