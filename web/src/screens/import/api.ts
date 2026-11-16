import { useQuery } from '@tanstack/react-query';
import { api, del, json } from '../../api/client';

export type Field = 'date' | 'description' | 'memo' | 'amount' | 'debit' | 'credit' | 'direction' | 'status' | 'id';
export type Mapping = Partial<Record<Field, number>>;
export type Verdict = { verdict: 'negate' | 'as_is' | null; lean: 'positive' | 'negative' | null };
export type DateOption = { format: string; label: string; reading: string };
export type StagedLayout = {
  id: number | null; key: string; header: string[]; mapping: Mapping; negate: boolean | null; date_format: string | null;
  reading: string | null; sign_fixed: boolean; sign: { credit: Verdict; bank: Verdict };
  date_question: { example: string; options: DateOption[] } | null; sample: string[][];
};
export type LeftOut = { pending: number; balance: number; totals: number; currency: number };
export type StagedFile = {
  token: string | null; name: string; bytes: number; kind: 'csv' | 'ofx' | null;
  state: 'known' | 'remembered' | 'builtin' | 'new' | 'error'; label: string | null; card: boolean; rows: number;
  from: string | null; to: string | null; imported_before: string | null; account_id: number | null;
  suggested_by: 'hint' | 'layout' | 'digits' | 'name' | null; layout: StagedLayout | null;
  errors: { row: number; text: string }[]; unreadable: number; held: string | null; left_out: LeftOut; error: string | null;
};
export type Staged = { batch: string; files: StagedFile[] };
export type SentLayout = { mapping: Mapping; negate: boolean | null; date_format: string | null };
export type FileChoice = { token: string; account_id: number; layout: SentLayout | null; include: number[] };
export type StatementChoice = { id: number; account_id: number; include: number[] };
export type PreviewBody = { batch: string | null; files: FileChoice[]; statements: StatementChoice[]; simplefin_include: number[] };
export type LookRow = { token: string; row: number; posted_at: string; amount_cents: number; description: string };
export type SameRow = LookRow & {
  match: { where: 'steward' | 'file'; posted_at: string; amount_cents: number; description: string; account: string };
};
export type PreviewFile = {
  token: string; name: string; account_id: number; new: number; already: number; simplefin: number; same: number;
  from: string | null; to: string | null; errors: { row: number; text: string }[]; unreadable: number; held: string | null;
  left_out: LeftOut;
};
export type PreviewReply = {
  digest: string; new: number; writes?: number; already: number; simplefin: { n: number; since: string | null }; same: number;
  unreadable: number; from: string | null; to: string | null; accounts: number; months: number; files: PreviewFile[];
  holdings?: { n: number; kept: number; rows: { account: string; as_of: string; count: number; kept: boolean }[] };
  balances?: { n: number; kept: number; rows: { account: string; as_of: string; cents: number; kept: boolean }[] };
  look: {
    same: SameRow[]; same_more: number; already: LookRow[]; already_more: number;
    simplefin: { account_id: number; account: string; since: string; rows: LookRow[]; more: number }[];
  };
};
export type CommitReply = {
  set_id: number; imported: number; waiting?: number; accounts: number; account: string | null; skipped: number; months: number;
  batch_ids: number[]; statements: number; added_up: number; kept_balances: string[]; kept_holdings?: string[];
};
export type BatchFile = {
  id: number; account_id: number; account_name: string | null; filename: string; format: string; row_count: number;
  imported_at: string; imported_by: number; rolled_back_at: string | null;
  period_end?: string | null; check_state?: 'adds_up' | 'anyway' | null; check_gap_cents?: number | null;
};
export type ImportGroup = {
  set_id: number | null; imported_at: string; imported_by: number; rolled_back_at: string | null; files: BatchFile[];
};

/** Plan Engineering choice 22: the file is the request body itself, never multipart, so the NAS never spools it to disk. */
export function stageFile(file: File, batch: string | null): Promise<Staged> {
  const q = batch ? `?batch=${encodeURIComponent(batch)}` : '';
  return api<Staged>(`/api/import/files${q}`, {
    method: 'POST', body: file,
    headers: { 'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name) },
  });
}
export const stagedBatch = (batch: string) => api<Staged>(`/api/import/batch/${encodeURIComponent(batch)}`);
export const dropFile = (token: string) => api<void>(`/api/import/files/${encodeURIComponent(token)}`, del());
export const previewBatch = (body: PreviewBody) => api<PreviewReply>('/api/import/batch/preview', json(body));
export const commitBatch = (body: PreviewBody & { digest: string }) => api<CommitReply>('/api/import/batch/commit', json(body));
export const rollbackSet = (id: number) => api<{ deleted: number }>(`/api/import/sets/${id}/rollback`, { method: 'POST' });
export const rollbackFile = (id: number) => api<{ deleted: number }>(`/api/import/batches/${id}/rollback`, { method: 'POST' });
export const useImports = () =>
  useQuery({ queryKey: ['batches'], queryFn: () => api<{ imports: ImportGroup[] }>('/api/import/batches') });
/** Today's list: what an import or its Undo changes. */
export const REFRESH = ['batches', 'accounts', 'summary', 'history', 'transactions', 'review', 'events', 'spending', 'import-layouts', 'welcome'];
