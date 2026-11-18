import type { ItemStatus, PayerBalance, TripReason, TripRow, TripSummary } from '../../api/types';
import { CATEGORY_GROUPS, label } from '../../lib/categories';
import { dateLabel, dollars, money } from '../../lib/format';
import * as C from './copy';
import { addDays } from '../../lib/today';

/** Fills {placeholders}; one that isn't given stays as it is. */
export const fill = (s: string, vars: Record<string, string | number>) =>
  s.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m));

/** A YYYY-MM-DD day as a local date (the server's household day, never the browser's clock). */
export function dayOf(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d);
}

export function daysBefore(iso: string, n: number): string {
  return addDays(iso, -n);
}

export const statusWord = (s: ItemStatus | null): string =>
  s === 'paid' ? C.PAID_BACK : s === 'partly' ? C.PARTLY : s === 'waiting' ? C.WAITING : C.NO_CHARGES;

/** "Acme owes you $1,240.35", or the spec's line when the payer has paid more than has been marked. */
export const owedLine = (p: PayerBalance): string => (p.owed_cents < 0
  ? fill(C.PAID_MORE, { payer: p.name, amount: money(-p.owed_cents) })
  : fill(C.OWES_YOU, { payer: p.name, amount: money(p.owed_cents) }));

/** "$2,030 marked since Sep 1 · $790 paid back · last repayment Oct 15": whole dollars, parts with nothing left out. */
export function detailLine(p: PayerBalance, today: Date): string {
  const parts: string[] = [];
  if (p.since) parts.push(fill(C.MARKED_SINCE, { amount: dollars(p.marked_cents), date: dateLabel(p.since, today) }));
  parts.push(fill(C.PAID_BACK_N, { amount: dollars(p.repaid_cents) }));
  if (p.last_repaid_on) parts.push(fill(C.LAST_REPAYMENT, { date: dateLabel(p.last_repaid_on, today) }));
  return parts.join(' · ');
}

/** The owed bar's fill, 0 to 1: what came back (repayments, refunds, settlements) of what was marked. */
export const barFill = (p: PayerBalance): number =>
  (p.marked_cents > 0 ? Math.min(1, Math.max(0, p.cleared_cents / p.marked_cents)) : 0);

export const tripDates = (t: TripSummary, today: Date) =>
  fill(C.TRIP_DATES, { start: dateLabel(t.start, today), end: dateLabel(t.end, today) });
export const chargesWord = (n: number) => (n === 1 ? C.ONE_CHARGE : fill(C.N_CHARGES, { n }));

/** "Chicago trip" from "Chicago, IL"; nothing without a city. */
export function defaultTripName(city: string): string {
  const c = city.split(',')[0].trim();
  return c ? fill(C.TRIP_NAME_DEFAULT, { city: c }) : '';
}

const NOT_SPENDING = new Set(['income', 'interest', 'business_income', 'reimbursement', 'transfer', 'investment']);
/** Settle's choices: Spending's categories, in the picker's order. */
export const SETTLE_CATEGORIES: readonly string[] = CATEGORY_GROUPS.flatMap((g) => g.keys).filter((k) => !NOT_SPENDING.has(k));

/** A trip's review list (Task 12). */
export const GROUPS = ['booked', 'likely', 'home', 'unsure'] as const;
export const GROUP_TITLES: Record<TripRow['group'], string> = {
  booked: C.G_BOOKED, likely: C.G_LIKELY, home: C.G_HOME, unsure: C.G_UNSURE,
};

export function reasonText(r: TripReason): string {
  switch (r.why) {
    case 'booked': return C.R_BOOKED;
    case 'says': return fill(C.R_SAYS, { place: r.place ?? '' });
    case 'flight': return C.R_FLIGHT;
    case 'hotel': return C.R_HOTEL;
    case 'travel': return C.R_TRAVEL;
    case 'ride': return C.R_RIDE;
    case 'new': return C.R_NEW;
    case 'regular': return C.R_REGULAR;
    case 'home_only': return label(r.category ?? '');
    case 'refund': return C.R_REFUND;
    default: return C.R_UNSURE;
  }
}

/** The mark button's count and total: ticked charges less ticked refunds. */
export function markTotals(rows: Pick<TripRow, 'id' | 'amount_cents'>[], ticked: ReadonlySet<number>): { n: number; total: number } {
  const on = rows.filter((r) => ticked.has(r.id));
  return { n: on.length, total: on.reduce((s, r) => s - r.amount_cents, 0) };
}
