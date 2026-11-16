// Look into and Settings → Watching (src/steward/api/flags.py, watching.py). Money is cents.
import { useInfiniteQuery, useQuery, type QueryClient } from '@tanstack/react-query';
import { api, json, patch } from '../../api/client';

export type CheckKey = 'scam' | 'payee' | 'large' | 'unusual' | 'cash' | 'monthly' | 'duplicate' | 'deposit' | 'premium' | 'account' | 'low';
export type FlagStatus = 'open' | 'checking' | 'expected' | 'handled' | 'arrived';
export type Ran = { short: string; line: string; home_empty: string; empty: string };
export type FlagRow = {
  id: number; check: CheckKey; check_label: string; icon: string; severity: 'urgent' | 'normal'; urgent: boolean;
  status: FlagStatus; status_label: string; by: string | null; note: string | null; note_by: string | null;
  summary: string; title: string; place: string; when: string; flagged: string; amount_cents: number | null;
  done: boolean; account_id: number | null;
};
export type FlagList = {
  show: 'open' | 'done'; flags: FlagRow[]; counts: { open: number; done: number };
  checks: { check: CheckKey; label: string; count: number }[]; accounts: { id: number; name: string }[];
  next_offset: number | null; ran: Ran | null; mail_ready: boolean | null; can_edit: boolean;
};
export type Scope = { key: 'about' | 'any' | 'this'; title: string; line: string };
export type MiniTxn = { name: string; amount_cents: number; meta: string; raw?: string };
export type FlagPage = FlagRow & {
  why: string; fact: string; also: { check: CheckKey; label: string; icon: string; detail: string }[];
  flagged_at: string; status_at: string | null;
  transaction: { removed: boolean; id: number | null; payee: string | null; amount_cents: number | null; date_label: string | null;
    account: string | null; joint_names: string | null; raw: string | null; category_label: string | null } | null;
  others: MiniTxn[]; earlier: { heading: string; line: string; rows: MiniTxn[] } | null; payments: MiniTxn[];
  related: { id: number; name: string; sub: string; amount_cents: number | null; status: string } | null;
  related_line: string | null; expected: { scopes: Scope[]; fixed: string | null; help: string } | null;
  expected_note: string | null; known: { id: number; label: string } | null;
  history: { id: string; icon: string; text: string; note: string | null; at: string }[];
  can_edit: boolean; viewer_line: string | null; done_line?: string | null;
};
export type Floor = { item_id: number; name: string; sub: string; balance_cents: number | null; floor_cents: number | null; under: boolean };
export type KnownPayee = { id: number; payee: string; range: string; added: string; note: string | null };
export type Person = { user_id: number; name: string; role: 'manager' | 'viewer'; role_label: string; urgent: boolean; summary: boolean; can_change: boolean; is_me: boolean };
export type WatchSettings = {
  large_cents: number; cash_alert_floor_cents: number; default_cash_floor_cents: number; default_cents: number; floors: Floor[]; known: KnownPayee[];
  mail: { ready: boolean; last_sent: string | null; failure: { title: string; line: string } | null };
  people: Person[]; can_edit: boolean;
};

export function useFlags(show: 'open' | 'done', check?: string, accountId?: string) {
  return useInfiniteQuery({
    queryKey: ['flags', 'list', show, check ?? '', accountId ?? ''],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => {
      const qs = new URLSearchParams({ show });
      if (check) qs.set('check', check);
      if (accountId) qs.set('account_id', accountId);
      if (pageParam) qs.set('offset', String(pageParam));
      return api<FlagList>(`/api/flags?${qs}`);
    },
    getNextPageParam: (last) => last.next_offset ?? undefined,
  });
}
export const useFlag = (id: number) =>
  useQuery({ queryKey: ['flags', 'one', id], queryFn: () => api<FlagPage>(`/api/flags/${id}`), enabled: Number.isFinite(id) });
export const useWatching = () => useQuery({ queryKey: ['watching'], queryFn: () => api<WatchSettings>('/api/watching') });

export const markExpected = (id: number, scope: string, note: string) => api<FlagPage>(`/api/flags/${id}/expected`, json({ scope, note }));
export const markHandled = (id: number, note: string) => api<FlagPage>(`/api/flags/${id}/handled`, json({ note }));
export const markChecking = (id: number, note: string) => api<FlagPage>(`/api/flags/${id}/checking`, json({ note }));
export const changeNote = (id: number, note: string) => api<FlagPage>(`/api/flags/${id}/note`, json({ note }));
export const reopenFlag = (id: number) => api<FlagPage>(`/api/flags/${id}/reopen`, json({}));
export const setCashFloor = (cents: number) => api<WatchSettings>('/api/watching/cash-floor', patch({ cents }));
export const setLarge = (cents: number) => api<WatchSettings>('/api/watching/large', patch({ cents }));
export const setFloor = (itemId: number, cents: number | null) =>
  api<WatchSettings>(`/api/watching/floors/${itemId}`, { method: 'PUT', body: JSON.stringify({ cents }) });
export const removeKnown = (id: number, note: string) => api<WatchSettings>(`/api/watching/known/${id}/remove`, json({ note }));
export const setEmails = (userId: number, body: { urgent?: boolean; summary?: boolean }) => api<WatchSettings>(`/api/watching/emails/${userId}`, patch(body));
export const stopMyEmails = () => api<WatchSettings>('/api/watching/emails/stop', { method: 'POST' });
export const sendTestEmail = () => api<{ sent_to: string }>('/api/watching/test-email', json({}));

/** After a flag action or a Watching change: the flags (and Home's count), Watching, the change record, Home and items. */
export async function refreshFlags(qc: QueryClient) {
  await Promise.all([
    qc.invalidateQueries({ queryKey: ['flags'] }),
    qc.invalidateQueries({ queryKey: ['watching'] }),
    qc.invalidateQueries({ queryKey: ['changes'] }),
    qc.invalidateQueries({ queryKey: ['inventory'] }),
  ]);
}
