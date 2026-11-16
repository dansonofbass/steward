import type { Txn } from '../../api/types';
import { label } from '../../lib/categories';
import { ALL_SQUARE, STAMP_SORTED } from '../../lib/copy';
import { dateLabel } from '../../lib/format';
import { allSquare, reimburseFacts, rich, settleOffer, type Part } from '../../lib/receipt';
import * as C from './copy';
import type { SortDone } from './useReviewActions';
import type { VisitRow } from './visitList';

/** Phase 17 spec 3.7: a sort's cheer, its line and whether it is the rare golden one. */
export type ToastCheer = { line: string; golden: boolean };
/** What the toast says (review focus, The toast and Copy): an optional stamp tag, the line, Settle when offered, and
 *  the cheer on every 3rd to 5th sort. */
export type ToastBody = { tag: string | null; parts: Part[]; settle: { id: number; cents: number } | null; cheer?: ToastCheer | null };
type Named = Pick<Txn, 'nickname' | 'merchant' | 'raw_description'>;

/** The display name: the nickname, then the merchant, then the bank's text. */
export const displayName = (t: Named): string => t.nickname || t.merchant || t.raw_description;
export const likeLine = (n: number): string => (n === 1 ? C.ALSO_LIKE_ONE : C.ALSO_LIKE_N.replace('{n}', String(n)));
const SPACE: Part = { text: ' ', bold: false };

/** A sort's toast. The count is the server's `applied`. A reimbursement adds today's facts (REIMB_FACTS and family) and
 *  Settle when offered; a repayment that brings the payer to $0 says "All square with {payer}." instead (P17). */
export function sortToast(txn: Txn, d: SortDone): ToastBody {
  const square = d.reply.result?.reimburse;
  if (allSquare(square)) return { tag: null, parts: rich(ALL_SQUARE, { payer: square.payer }), settle: null };
  const rr = d.reply.result?.reimburse ?? null;   // read again: the guard above would narrow `square` to nothing
  const category = label(d.reply.result?.category ?? d.category);
  const line = rich(d.applied > 0 ? C.TOAST_SORTED_N : C.TOAST_SORTED, { name: displayName(txn), n: d.applied, category });
  const facts = rr ? reimburseFacts(rr, d.category, txn.amount_cents) : [];
  const offer = settleOffer(rr);
  return { tag: STAMP_SORTED, parts: facts.length ? [...line, SPACE, ...facts] : line,
    settle: rr && offer !== null ? { id: rr.reimburser_id, cents: offer } : null };
}

export const snoozeToast = (until: string, today: Date): ToastBody =>
  ({ tag: null, parts: rich(C.TOAST_SNOOZED, { date: dateLabel(until, today) }), settle: null });
export const ignoreToast = (txn: Named): ToastBody =>
  ({ tag: null, parts: rich(C.TOAST_IGNORED, { name: displayName(txn) }), settle: null });
/** A message as a toast (a refused Undo, a saved note). */
export const plainToast = (text: string): ToastBody => ({ tag: null, parts: [{ text, bold: false }], settle: null });

/** A slim row's words after its stamp tag (review focus, The list's slim rows). */
export function slimText(row: VisitRow, today: Date): { tag: string; parts: Part[] } {
  const name = displayName(row.txn);
  const o = row.outcome;
  switch (o.kind) {
    case 'sorted':
      return { tag: STAMP_SORTED, parts: rich(o.n > 0 ? C.SLIM_SORTED_N : C.SLIM_SORTED, { name, n: o.n, category: label(o.category) }) };
    case 'matched':
    case 'bulk':
      return { tag: STAMP_SORTED, parts: rich(C.SLIM_SORTED, { name, category: label(o.category) }) };
    case 'snoozed':
      return { tag: C.TAG_SNOOZED, parts: rich(C.SLIM_SNOOZED, { name, date: dateLabel(o.until, today) }) };
    case 'ignored':
      return { tag: C.TAG_IGNORED, parts: rich(C.SLIM_NAME, { name }) };
    case 'elsewhere':
    case 'waiting':
      return { tag: STAMP_SORTED, parts: rich(C.SLIM_NAME, { name }) };
  }
}
