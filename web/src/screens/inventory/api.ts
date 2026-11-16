// The inventory's API (src/steward/api/inventory*.py, suggestions.py, tax_forms.py, changes.py). Money is cents.
import { useInfiniteQuery, useQuery, type QueryClient } from '@tanstack/react-query';
import { resolveApiPath } from '../../api/book';
import { ApiError, NETWORK_MESSAGE, api, del, json, notifyUnauthorized, patch } from '../../api/client';

export type ItemKind = 'account' | 'income' | 'insurance' | 'document' | 'contact';
export type ItemStatus = 'confirmed' | 'needs_checking' | 'closed';
export type DataSource = 'feed' | 'statement' | 'manual';
export type TotalGroup = 'cash' | 'investments' | 'retirement' | 'property' | 'debts';
export type Ref = { id: number; label: string };
export type ItemRow = {
  id: number; kind: ItemKind; name: string; owner: string; owner_label: string; institution: string | null;
  last4: string | null; status: ItemStatus; data_source: DataSource | null; type: string | null; type_label: string | null;
  type_word: string | null; sub: string; amount_cents: number | null; amount_per: 'mo' | '3 mo' | '6 mo' | 'yr' | null;
  monthly_cents: number | null; counts_in_totals: boolean; no_balance: boolean; total_group: TotalGroup | null;
  updated_on: string; check_reason: string | null; account_id: number | null;
};
export type FileRow = { id: number; name: string; content_type: string; label: string; size: number; size_label: string; uploaded_on: string; uploaded_by: string | null };
export type ChangeRow = {
  id: string; at: string; who: string | null; icon: string; text: string; item: (Ref & { path?: string }) | null;
  diffs: { label: string; before: string | null; after: string | null }[]; lines: string[]; note: string | null; summary: string;
};
export type ItemDetail = ItemRow & {
  details: Record<string, unknown>; login_kept_in: string | null; notes: string | null; has_full_number: boolean;
  closed_on: string | null; closed_reason: string | null;
  refs: { lands_in_id: Ref | null; paid_from_id: Ref | null; prepared_by_id: Ref | null };
  looks_after: Ref[]; money_in_here: { id: number; name: string }[]; paid_from_here: { id: number; name: string }[];
  linked_items: { id: number; name: string }[]; joint_names: string | null; added_line: string;
  balance: { cents: number; line: string } | null;
  holdings: { as_of: string; rows: { symbol: string | null; name: string | null; value_cents: number }[] } | null;
  transactions: { id: number; name: string; amount_cents: number; posted_at: string; category: string }[];
  matched: { heading: string; match_text: string; rows: { posted_at: string; amount_cents: number; note: string | null }[]; last_paid: string | null } | null;
  files: FileRow[]; history: ChangeRow[];
};
export type SuggestionSummary = { count: number; phrases: string[]; found_in: string };
export type InventoryList = { items: ItemRow[]; suggestions: SuggestionSummary | null };
export type FlowRow = { item_id: number; name: string; cents: number; per: string; sub: string; status: ItemStatus };
export type Overview = {
  net_worth_cents: number; counted_line: string; fresh_line: string | null;
  needs_checking: { count: number; labels: string[] }; suggestions: { count: number; found_in: string } | null;
  totals: { key: TotalGroup; label: string; cents: number; note: string }[];
  incoming: { monthly_cents: number; rows: FlowRow[]; foot: string | null };
  outgoing: { monthly_cents: number; rows: FlowRow[]; foot: string };
  recent: ChangeRow[];
};
export type Suggestion = {
  id: number; kind: 'income' | 'insurance' | 'account'; payer: string; eyebrow: string; title: string; why: string;
  evidence: { raw: string; amount_cents: number; posted_at: string; account: string }[]; forms: string[];
  phrase: string; noun: string; count: number; prefill: Record<string, unknown>; filled_line: string; likely_ids: number[];
};
export type Answer = { id: number; icon: 'check' | 'x'; line: string; sub: string };
export type Dismissed = { id: number; payer: string; kind_label: string; answered_on: string | null; answered_by: string | null };
export type ChangePage = { changes: ChangeRow[]; next: string | null; people: { id: number; name: string }[] };
export type TaxResult = { headline: string; detail: string; suggestion_id: number | null; item_id: number | null };
export type UploadResult = { file: FileRow; item: ItemDetail | null; looks_like_tax_form: boolean };

export const useInventory = () => useQuery({ queryKey: ['inventory', 'list'], queryFn: () => api<InventoryList>('/api/inventory') });
export const useOverview = () => useQuery({ queryKey: ['inventory', 'overview'], queryFn: () => api<Overview>('/api/inventory/overview') });
export const useItem = (id: number, enabled = true) =>
  useQuery({ queryKey: ['inventory', 'item', id], queryFn: () => api<ItemDetail>(`/api/inventory/items/${id}`), enabled: enabled && Number.isFinite(id) });
export const useSuggestions = (enabled = true) =>
  useQuery({ queryKey: ['inventory', 'suggestions'], queryFn: () => api<{ suggestions: Suggestion[] }>('/api/inventory/suggestions'), enabled });
export const useDismissed = () =>
  useQuery({ queryKey: ['inventory', 'dismissed'], queryFn: () => api<{ dismissed: Dismissed[] }>('/api/inventory/suggestions/dismissed') });

export type ChangeFilters = { user_id?: string; kind?: string };
export function useChanges(filters: ChangeFilters) {
  return useInfiniteQuery({
    queryKey: ['changes', filters],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const qs = new URLSearchParams();
      if (filters.user_id) qs.set('user_id', filters.user_id);
      if (filters.kind) qs.set('kind', filters.kind);
      if (pageParam) qs.set('before', pageParam);
      return api<ChangePage>(`/api/changes${qs.toString() ? `?${qs}` : ''}`);
    },
    getNextPageParam: (last) => last.next,
  });
}

export const addItem = (body: Record<string, unknown>) => api<ItemDetail>('/api/inventory/items', json(body));
export const editItem = (id: number, body: Record<string, unknown>) => api<ItemDetail>(`/api/inventory/items/${id}`, patch(body));
export const closeItem = (id: number, body: { closed_on: string; why: string }) => api<ItemDetail>(`/api/inventory/items/${id}/close`, json(body));
export const reopenItem = (id: number) => api<ItemDetail>(`/api/inventory/items/${id}/reopen`, json({}));
export const revealNumber = (id: number) => api<{ number: string }>(`/api/inventory/items/${id}/full-number`, json({}));
export const removeFile = (id: number) => api<void>(`/api/inventory/files/${id}`, del());
export const fileHref = (slug: string, id: number) => `/api/b/${encodeURIComponent(slug)}/inventory/files/${id}`;
export const dismissSuggestion = (id: number) => api<{ answer: Answer }>(`/api/inventory/suggestions/${id}/dismiss`, json({}));
export const linkSuggestion = (id: number, itemId: number, confirm: boolean) =>
  api<{ answer: Answer }>(`/api/inventory/suggestions/${id}/link`, json({ item_id: itemId, confirm }));
export const undoSuggestion = (id: number) => api<{ ok: boolean }>(`/api/inventory/suggestions/${id}/undo`, json({}));
export const saveTaxForm = (body: Record<string, unknown>) => api<TaxResult>('/api/inventory/tax-forms', json(body));
export function importTaxForms(file: File) {
  const fd = new FormData();
  fd.append('file', file);
  return api<{ saved: number; results: TaxResult[] }>('/api/inventory/tax-forms/csv', { method: 'POST', body: fd });
}

/** Upload with progress (fetch can't report it). Rejects with ApiError carrying the server's words, or AbortError. */
export function uploadFile(file: File, opts: { itemId?: number; confirm?: boolean }, onProgress: (sent: number, total: number) => void,
  signal?: AbortSignal): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', resolveApiPath('/api/inventory/files'));
    xhr.setRequestHeader('Accept', 'application/json');
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded, e.total); };
    xhr.onload = () => {
      let body: unknown = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(body as UploadResult);
      if (xhr.status === 401) notifyUnauthorized();
      const error = (body as { error?: unknown } | null)?.error;
      reject(new ApiError(xhr.status, typeof error === 'string' ? error : `Something went wrong (${xhr.status}).`, body));
    };
    xhr.onerror = () => reject(new ApiError(0, NETWORK_MESSAGE));
    xhr.onabort = () => reject(new DOMException('Stopped', 'AbortError'));
    signal?.addEventListener('abort', () => xhr.abort());
    const fd = new FormData();
    fd.append('file', file);
    if (opts.itemId !== undefined) fd.append('item_id', String(opts.itemId));
    if (opts.confirm) fd.append('confirm', 'true');
    xhr.send(fd);
  });
}

/** After a write: the inventory, its overview and items, the change record and the accounts list are stale. Pass
 *  suggestions: false to keep the answered cards on the suggestions page in place. */
export async function refreshInventory(qc: QueryClient, opts: { suggestions?: boolean } = {}) {
  const keepSuggestions = opts.suggestions === false;
  await Promise.all([
    qc.invalidateQueries({ queryKey: ['inventory'], predicate: (q) => !(keepSuggestions && q.queryKey[1] === 'suggestions') }),
    qc.invalidateQueries({ queryKey: ['changes'] }),
    qc.invalidateQueries({ queryKey: ['accounts'] }),
  ]);
}
