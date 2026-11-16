// Settings → Chat (src/steward/api/chat.py). Money arrives as words and cents from the server.
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { api, json } from '../../api/client';

export type GatewayState = 'ok' | 'away' | 'not_set_up' | 'paused' | 'stopped';
export type GatewayChecks = { redaction: boolean; key: boolean; categorizer: boolean };
export type ChatStatus = {
  on: boolean; can_change: boolean; changed: { by: string | null; at: string; line: string } | null; seen: boolean;
  disclosure: string; off_line: string;
  gateway: { state: GatewayState; line: string; last_answered: string | null; checked: string | null; checks: GatewayChecks | null; away_long: boolean; pdf_place?: 'local' | 'gateway'; mcp?: boolean | null; paired?: boolean; url_set?: boolean };
  budget: { line: string; warn: string | null; cap_line: string | null; spent_cents: number; cap_cents: number; questions: number; model: string } | null;
  can_budget: boolean; models: { id: string; label: string }[];
  members: string[]; managers: string[]; sent_month: { requests: number; last: string | null };
  /** The members but the person reading: who sees the disclosure later (INS-18). */
  others?: string[];
};
export type SentKind = 'question' | 'results' | 'store_rows' | 'prewarm' | 'history';
export type SentRow = { key: string; at: string; when: string; day: string; who: string; channel: string; what: string; kind: SentKind; conversation: string | null; size: string };
export type SentPage = { requests: SentRow[]; next_offset: number | null; people: { id: number; name: string }[] };
export type SentDetail = {
  key: string; who: string; when: string; approved_by: string | null; conversation: string | null; size: string; checks: string[];
  aliases: { alias: string; label: string }[];
  parts: { id: number; part: string; label: string; sha256: string; bytes: number; payload: unknown }[];
};

export type Usage = { usage: { months: { month: string; spent: string; questions: number }[];
  by_book: { book: string; spent: string; questions: number }[];
  by_person: { book: string; person: string; spent: string; questions: number }[] } | null };

export const useChatStatus = (enabled = true) => useQuery({ queryKey: ['chat', 'status'], queryFn: () => api<ChatStatus>('/api/chat'), enabled });
export const useUsage = () => useQuery({ queryKey: ['chat', 'usage'], queryFn: () => api<Usage>('/api/chat/usage') });
export type SentFilters = { who: number | null; what: string | null };
export const useSent = (f: SentFilters) => useInfiniteQuery({
  queryKey: ['chat', 'sent', f.who, f.what], initialPageParam: 0,
  queryFn: ({ pageParam }) => {
    const p = new URLSearchParams();
    if (pageParam) p.set('offset', String(pageParam));
    if (f.who !== null) p.set('who', String(f.who));
    if (f.what) p.set('what', f.what);
    const qs = p.toString();
    return api<SentPage>(`/api/chat/sent${qs ? `?${qs}` : ''}`);
  },
  getNextPageParam: (last) => last.next_offset ?? undefined,
});
export const useSentDetail = (key: string | null) => useQuery({
  queryKey: ['chat', 'sent', 'one', key], enabled: key !== null,
  queryFn: () => api<SentDetail>(`/api/chat/sent/${encodeURIComponent(key ?? '')}`),
});
export const setChatOn = (on: boolean) => api<ChatStatus>('/api/chat/on', json({ on }));
export const setBudget = (body: { cap_dollars: number; model: string }) => api<{ ok: true }>('/api/chat/budget', json(body));

/** Another book's chat status, for Settings → Chat's "Chat in each book" (plan B ruling 21). */
export const useBookStatus = (slug: string) => useQuery({
  queryKey: ['chat', 'status-of', slug], queryFn: () => api<ChatStatus>(`/api/b/${encodeURIComponent(slug)}/chat`),
});
export const setChatOnIn = (slug: string, on: boolean) => api<ChatStatus>(`/api/b/${encodeURIComponent(slug)}/chat/on`, json({ on }));
