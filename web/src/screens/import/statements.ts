import { useQuery } from '@tanstack/react-query';
import { api, del, json, patch } from '../../api/client';
import { gw } from '../../lib/gatewayName';
import * as C from './copy';
import { count, monthDay } from './logic';

export type GatewayState = 'answering' | 'waiting' | 'old' | 'unpaired';
export type StatementLine = {
  id: number; name: string; bytes: number; pages: number | null; added_by: string | null; kind: 'text' | 'scan' | 'mixed' | null;
  state: 'queued' | 'reading' | 'waiting' | 'layout' | 'off' | 'holdings' | 'ready' | 'error' | 'cleared';
  error: string | null; error_text: string | null; label: string | null; statement_kind: string | null;
  period: { start: string; end: string } | null; rows: number | null; holdings: number | null; balance_cents: number | null;
  gap_cents: number | null; needs_account?: boolean; anyway: boolean; progress: { done: number; of: number } | null; last4: string | null;
  account_id: number | null; suggested_by: string | null; imported_before: string | null; expires_at: string; removed: boolean;
  needs_model?: boolean;
};
export type StatementList = { statements: StatementLine[]; gateway: GatewayState; reading?: 'local' | 'gateway' };

export const MAX_PDF = 15 * 1024 * 1024;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export const isPdf = (f: File) => f.type === 'application/pdf' || /\.pdf$/i.test(f.name);
export const money = (cents: number) =>
  '$' + (Math.abs(cents) / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export function monthYear(iso: string): string {
  const [y, m] = iso.slice(0, 10).split('-').map(Number);
  return `${MONTHS[m - 1]} ${y}`;
}

/** P1: the PDF is the request body itself, never multipart, so the NAS never spools it to disk. */
export function uploadStatement(file: File, batch: string | null): Promise<{ statement: StatementLine }> {
  const q = batch ? `?batch=${encodeURIComponent(batch)}` : '';
  return api(`/api/import/statements${q}`, {
    method: 'POST', body: file, headers: { 'Content-Type': 'application/pdf', 'X-Filename': encodeURIComponent(file.name) },
  });
}
export const patchStatement = (id: number, body: { account_id?: number | null; anyway?: boolean }) =>
  api<{ statement: StatementLine }>(`/api/import/statements/${id}`, patch(body));
export const retryStatement = (id: number) => api<{ statement: StatementLine }>(`/api/import/statements/${id}/retry`, json({}));
export const removeStatement = (id: number) => api<void>(`/api/import/statements/${id}`, del());
export const finalRemove = (id: number) => api<void>(`/api/import/statements/${id}?final=1`, del());
export const restoreStatement = (id: number) => api<{ statement: StatementLine }>(`/api/import/statements/${id}/restore`, json({}));

const moving = (d: StatementList | undefined) => !!d?.statements.some((s) => !s.removed && (s.state === 'queued' || s.state === 'reading'));

const waiting = (d: StatementList | undefined) => !!d?.statements.some((s) => !s.removed && s.state === 'waiting');

/** P45 and remote-reading P70: every 3 s while a line reads, every 30 s while one waits for the gateway (so it moves on
 *  its own when the gateway is back), and only while the tab is visible. */
export const pollEvery = (d: StatementList | undefined): number | false => (moving(d) ? 3000 : waiting(d) ? 30_000 : false);

export const useStatements = () => useQuery({
  queryKey: ['statements'], queryFn: () => api<StatementList>('/api/import/statements'),
  refetchInterval: (q) => pollEvery(q.state.data), refetchIntervalInBackground: false,
});

export const RETRYABLE = ['page_failed', 'layout_failed', 'read_failed'];
export const isRetryable = (s: StatementLine) => s.state === 'error' && RETRYABLE.includes(s.error ?? '');
export const oldGatewayNote = (reading: StatementList['reading']) => gw(reading === 'gateway' ? C.ST_OLD_GATEWAY_PDF : C.ST_OLD_GATEWAY);

export const needsLook = (s: StatementLine) => !s.needs_account && (s.state === 'layout' || s.state === 'off' || s.state === 'holdings');
export const importable = (s: StatementLine) =>
  !s.removed && s.account_id !== null && (s.state === 'ready' || (s.state === 'off' && s.anyway));
export const waitingOnIt = (s: StatementLine) => !s.removed && !importable(s) && s.state !== 'error' && s.state !== 'cleared';

export function statementTag(s: StatementLine, gateway: GatewayState): string {
  let t: string;
  if (s.state === 'queued') t = C.ST_QUEUED;
  else if (s.state === 'reading') {
    t = s.progress ? C.ST_READING_SCAN.replace('{n}', String(s.progress.done + 1)).replace('{m}', String(s.progress.of))
      : s.pages === null ? C.READING : C.ST_READING_NEW;
  }
  else if (s.state === 'waiting') t = gateway === 'unpaired' ? C.ST_NOT_PAIRED : s.needs_model ? C.ST_NO_MODEL : C.ST_WAITING;
  else if (s.needs_account) t = C.ST_CHOOSE_ACCOUNT;
  else if (s.state === 'layout') t = C.ST_CHECK_LAYOUT;
  else if (s.state === 'holdings') t = C.ST_CHECK_HOLDINGS;
  else if (s.state === 'off') {
    const gap = s.gap_cents ? money(s.gap_cents) : null;
    t = !gap ? (s.anyway ? C.ST_CHECK_ROWS_ANYWAY : C.ST_CHECK_ROWS) : (s.anyway ? C.ST_ANYWAY : C.ST_OFF).replace('{gap}', gap);
  } else if (s.state === 'ready' && s.statement_kind === 'loan') {
    t = C.ST_READY_LOAN.replace('{label}', s.label ?? s.name).replace('{month}', s.period ? monthYear(s.period.end) : '')
      .replace('{amount}', money(s.balance_cents ?? 0));
  } else if (s.state === 'ready' && s.holdings !== null && (s.statement_kind === 'investment' || s.statement_kind === 'retirement')) {
    t = C.ST_READY_HOLDINGS.replace('{label}', s.label ?? s.name).replace('{month}', s.period ? monthYear(s.period.end) : '')
      .replace('{holdings}', s.holdings === 1 ? C.HOLDINGS_ONE : C.HOLDINGS_N.replace('{n}', count(s.holdings)));
  } else if (s.state === 'ready') {
    t = C.ST_READY_ROWS.replace('{label}', s.label ?? s.name).replace('{month}', s.period ? monthYear(s.period.end) : '')
      .replace('{n}', count(s.rows ?? 0));
  } else if (s.state === 'cleared') t = C.ST_CLEARED;
  else t = s.error_text ?? '';
  if (s.imported_before) t += C.TAG_BEFORE.replace('{date}', monthDay(s.imported_before));
  if (s.added_by) t += C.ST_ADDED_BY.replace('{name}', s.added_by);
  return gw(t);
}
