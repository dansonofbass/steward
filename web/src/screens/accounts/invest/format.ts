import { dateLabel, dollars } from '../../../lib/format';
import type { HoldingsOut, LimitLine, Sends } from './api';
import {
  FROM_IMPORT, FROM_INSTITUTION, FROM_STATEMENT, LIMIT_LINE, MAXED, MISSING, ON_PACE_SHORT, ON_PACE_TO_MAX, POSITION_ONE, POSITIONS_N, PREVIEW_DIFF, PREVIEW_NO_BALANCE, PREVIEW_SAME, RAISE, SENDS, SENDS_BALANCE, SENDS_HOLDINGS, SENDS_NO_HOLDINGS, SENDS_NO_TRANSACTIONS, SENDS_TRANSACTIONS,
} from './copy';

/** "Betterment sends: balance, transactions, no holdings" (investment views spec, What the bank sends). */
export function sendsLine(institution: string, s: Sends): string {
  const parts = [SENDS_BALANCE, s.transactions ? SENDS_TRANSACTIONS : SENDS_NO_TRANSACTIONS, s.holdings ? SENDS_HOLDINGS : SENDS_NO_HOLDINGS];
  return SENDS.replace('{institution}', institution).replace('{parts}', parts.join(', '));
}

/** 5.9 -> "+5.9%", -2 -> "−2.0%". */
export const pctText = (n: number): string => `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n).toFixed(1)}%`;

/** Basis points as a plain percent: 25 -> "0.25", 100 -> "1". */
export const bpText = (bp: number): string => String(Number((bp / 100).toFixed(2)));

/** "from Robo Invest, Oct 13" or "from betterment.csv's import, Oct 13". */
export function sourceLine(h: HoldingsOut, institution: string, today: Date): string {
  if (h.source === 'statement') return FROM_STATEMENT.replace('{month}', h.statement_month ?? '');
  const date = dateLabel(h.as_of, today);
  return h.source === 'import' && h.filename
    ? FROM_IMPORT.replace('{file}', h.filename).replace('{date}', date)
    : FROM_INSTITUTION.replace('{institution}', institution).replace('{date}', date);
}

/** "12 positions · $84,210; your balance is $84,210", or the difference; a difference under $1 reads as equal. */
export function previewLine(p: { count?: number; total_cents?: number; balance_cents?: number | null; difference_cents?: number | null }): string {
  const n = p.count ?? 0;
  const fill = (t: string) => t.replace('{positions}', n === 1 ? POSITION_ONE : POSITIONS_N.replace('{n}', String(n)))
    .replace('{total}', dollars(p.total_cents ?? 0));
  if (p.balance_cents === null || p.balance_cents === undefined) return fill(PREVIEW_NO_BALANCE);
  const diff = p.difference_cents ?? 0;
  return fill(Math.abs(diff) < 100 ? PREVIEW_SAME : PREVIEW_DIFF)
    .replace('{balance}', dollars(p.balance_cents)).replace('{difference}', dollars(Math.abs(diff)));
}

/** "$18,000 of $24,500 (2026 limit)". */
export const limitAmount = (l: LimitLine): string =>
  LIMIT_LINE.replace('{in}', dollars(l.in_cents)).replace('{limit}', dollars(l.limit_cents ?? 0)).replace('{year}', String(l.year));

/** On pace (investment views spec): maxed, on pace to max, or short with the raise that would max it. */
export function limitSentence(l: LimitLine): string {
  if (l.limit_cents === null) return MISSING;
  if (l.maxed) return MAXED.replace('{year}', String(l.year));
  if (l.short_cents <= 0) return ON_PACE_TO_MAX;
  const head = ON_PACE_SHORT.replace('{pace}', dollars(l.on_pace_cents)).replace('{short}', dollars(l.short_cents));
  return l.raise_pct ? `${head} ${RAISE.replace('{n}', String(l.raise_pct))}` : head;
}
