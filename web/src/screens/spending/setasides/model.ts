// Words for set-asides. The web shows what the API says: every amount, date and state arrives from the server, and
// "today" is the payload's as_of. Nothing here works out an amount, a due date or a state.
import type { EstimateOut, EstimatePreview, PreviewIn, SetAsideBody, SetAsideDetail, SetAsideDue, SetAsideEstimate, SetAsideKind, SetAsideList, SetAsidePayment, SetAsideRow, SetAsideState, SetAsideSuggestion, SpendingSetAside } from '../../../api/types';
import { label } from '../../../lib/categories';
import { dollars } from '../../../lib/format';
import { monthLong, monthName, monthNameOf, monthShort, monthShortOf } from '../../cashflow/months';
import { dollarsText, toHundredths } from '../../settings/money';
import { dayLabel, fill, joinNames } from '../format';
import * as C from './copy';

export { fill };
export { KIND_LABEL } from './copy';
export type Tone = 'soon' | 'behind' | 'track' | 'none';
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
/** Whole months from one ISO date's month to another's, on the calendar (December to January is 1). */
export const monthsBetween = (from: string, to: string) => (Number(to.slice(0, 4)) - Number(from.slice(0, 4))) * 12 + Number(to.slice(5, 7)) - Number(from.slice(5, 7));
/** "2026-11-01" → "Nov 1, 2026"; with `monthOnly`, a date on the 1st reads as its month, "Dec 2026". */
export const dateText = (iso: string, monthOnly = false) => (monthOnly && iso.slice(8, 10) === '01' ? `${monthShort(iso)} ${iso.slice(0, 4)}` : `${dayLabel(iso)}, ${iso.slice(0, 4)}`);
export const monthDay = (month: number, day: number) => `${monthShortOf(month)} ${day}`;
export const monthWord = (month: number) => monthNameOf(month);

export function costText(r: SetAsideRow): string {
  const amount = dollars(r.amount_cents);
  return r.kind === 'one_off' ? fill(C.COST_ONCE, { amount }) : r.kind === 'twice_yearly' ? fill(C.COST_TWICE, { amount }) : fill(C.COST_YEARLY, { amount });
}

/** A one-off is "About 2028"; a twice-yearly installment is its date; a yearly cost due on the 1st reads as its month
 *  (the mockups' Holidays, "next Dec 2026": a month is what a person knows about it). */
export function nextDueText(r: SetAsideRow): string {
  if (r.kind === 'one_off') return fill(C.ABOUT_YEAR, { year: r.due_year ?? '' });
  return r.next_due ? dateText(r.next_due, r.kind === 'yearly') : '';
}

/** Days from today in words: days up to 30, then weeks up to two months, then calendar months (so Mar 2027 from Oct 25
 *  is "in 5 months"). Before today it is days up to 30, then weeks. With `to` and `asOf`, the month count is on the calendar. */
export function whenWords(days: number, to?: string, asOf?: string): string {
  if (days === 0) return C.TODAY_WORD;
  if (days === 1) return C.IN_ONE_DAY;
  if (days < 0) {
    const ago = -days;
    if (ago === 1) return C.ONE_DAY_AGO;
    return ago <= 30 ? fill(C.DAYS_AGO, { n: ago }) : fill(C.WEEKS_AGO, { n: Math.round(ago / 7) });
  }
  if (days <= 30) return fill(C.IN_DAYS, { n: days });
  if (days < 60) return fill(C.IN_WEEKS, { n: Math.round(days / 7) });
  const months = to && asOf ? monthsBetween(asOf, to) : Math.round(days / 30.44);
  return months === 1 ? C.IN_ONE_MONTH : fill(C.IN_MONTHS, { n: months });
}

/** The row's second line: "next Nov 1, 2026, in 6 days", "About 2028, 26 months away", "Paid" for a paid one-off, or
 *  "Due Aug 2026" for an unpaid one-off past its due month (the server sends no next due date for either). */
export function dueWhen(r: SetAsideRow, asOf: string): string {
  if (r.paid !== null) return C.PAID;
  if (r.next_due === null) return fill(C.DUE_WAS, { month: `${monthShortOf(r.due_month ?? 12)} ${r.due_year ?? ''}` });
  if (r.kind === 'one_off') {
    const n = monthsBetween(asOf, r.next_due);
    if (n < 1) return `${nextDueText(r)}, ${whenWords(r.days_until ?? 0)}`;       // due this month, or overdue
    return `${nextDueText(r)}, ${n === 1 ? C.ONE_MONTH_AWAY : fill(C.MONTHS_AWAY, { n })}`;
  }
  return `${fill(C.NEXT, { date: nextDueText(r) })}, ${whenWords(r.days_until ?? 0, r.next_due, asOf)}`;
}

export const stateTone = (s: SetAsideState): Tone => (s === 'short' || s === 'not_paid' ? 'soon' : s === 'behind' ? 'behind' : s === 'on_track' ? 'track' : 'none');

/** The state in the list's words (decision 1), the same on the list, the detail and Spending. */
export function stateText(r: SetAsideRow): string {
  switch (r.state) {
    case 'short': return fill(C.DUE_SHORT, { when: whenWords(r.days_until ?? 0), amount: dollars(r.short_cents) });
    case 'behind': return fill(C.BEHIND_BY, { amount: dollars(r.behind_cents), put: dollars(r.put_away_cents), should: dollars(r.should_cents) });
    case 'not_paid': return fill(C.NOT_PAID_YET, { date: r.missed_due ? dayLabel(r.missed_due) : '' });
    case 'on_track': return r.should_cents === 0 ? C.ON_TRACK_NOTHING : C.ON_TRACK;
    default: return C.NO_ACCOUNT;
  }
}
/** The linked account's name, with the snapshot's date after it when the server says the balance is stale. */
export const accountWord = (r: SetAsideRow) => (r.account ? (r.account.stale && r.account.as_of ? `${r.account.name}, ${fill(C.BALANCE_FROM, { date: dayLabel(r.account.as_of) })}` : r.account.name) : null);
export const stateLine = (r: SetAsideRow) => { const a = accountWord(r); return a ? `${stateText(r)} · ${a}` : stateText(r); };

/** What the server has not verified about an estimate, in words ("lifespan to be checked"); empty when it checked both.
 *  Where the mockup names a source, an unchecked figure says this instead. */
export function checkNotes(e: Pick<SetAsideEstimate, 'to_check' | 'cost_to_check'>): string[] {
  return [e.to_check ? C.LIFESPAN_TO_CHECK : '', e.cost_to_check ? C.COST_TO_CHECK : ''].filter(Boolean);
}

export function headParts(l: SetAsideList): string[] {
  const parts = [l.count === 1 ? C.ONE_COST : fill(C.N_COSTS, { n: l.count })];
  if (l.yearly_cents > 0) parts.push(fill(C.YEARLY_LINE, { amount: dollars(l.yearly_cents) }));
  if (l.one_off_cents > 0) parts.push(fill(C.ONE_OFFS_LINE, { amount: dollars(l.one_off_cents) }));
  if (l.needs_look > 0) parts.push(l.needs_look === 1 ? C.ONE_NEEDS_A_LOOK : fill(C.NEED_A_LOOK, { n: l.needs_look }));
  return parts;
}

/** A suggestion's months in the year and its year's amount: "Apr, Dec · $4,210 a year" (P25). */
export function suggestionWhen(s: SetAsideSuggestion): string {
  return fill(C.SUGG_WHEN, { months: s.months.map(monthShortOf).join(', '), amount: dollars(s.yearly_cents) });
}

// ---- Spending's words (decision 10 and 16) ----
export const lowerFirst = (s: string) => (s.length > 1 && s[1] === s[1].toLowerCase() ? s[0].toLowerCase() + s.slice(1) : s);
export const setAsideHeadPart = (s: SpendingSetAside) => fill(C.SET_ASIDE_PART, { amount: dollars(s.monthly_cents) });
export function paidLine(s: SpendingSetAside): string | null {
  if (s.paid.length === 0) return null;
  const amount = dollars(s.paid.reduce((n, p) => n + p.cents, 0));
  return s.paid.length === 1 ? fill(C.PAID_LINE_ONE, { amount, name: lowerFirst(s.paid[0].name) }) : fill(C.PAID_LINE_MANY, { amount });
}
export function summaryRow(s: SpendingSetAside): { name: string; sub: string } {
  const name = `${s.count === 1 ? '1 cost' : `${s.count} costs`}, set aside this month`;
  if (s.paid.length > 0) {
    const paid = s.paid.map((p) => `${p.name} paid ${dayLabel(p.posted_at)}`).join(', ');
    return { name, sub: s.next ? `${paid} · next: ${s.next.name}, ${monthLong(s.next.next_due).split(' ')[0]}` : paid };
  }
  const more = s.count - s.names.length;
  const names = more > 0 ? `${s.names.join(', ')} and ${more} more` : joinNames(s.names);
  const money = [s.yearly_cents > 0 ? `${dollars(s.yearly_cents)} a year` : '', s.one_off_cents > 0 ? `${dollars(s.one_off_cents)} in one-offs` : ''].filter(Boolean).join(', ');
  return { name, sub: money ? `${names} · ${money}` : names };
}
// ---- One set-aside: the head, the schedule, the fund card, the payments ----

/** The detail head's line under the monthly figure. */
export function headLine(r: SetAsideRow, asOf: string): string[] {
  if (r.kind === 'one_off') {
    const planned = r.next_due ? dateText(r.next_due, true) : `${monthShortOf(r.due_month ?? 12)} ${r.due_year}`;
    let away = '';
    if (r.next_due) {
      const n = monthsBetween(asOf, r.next_due);
      away = n >= 1 ? `, ${n === 1 ? C.ONE_MONTH_AWAY : fill(C.MONTHS_AWAY, { n })}` : `, ${whenWords(r.days_until ?? 0)}`;
    }
    return [costText(r), `${fill(C.PLANNED_FOR, { month: planned })}${away}`];
  }
  const parts = [costText(r)];
  if (r.kind === 'twice_yearly') parts.push(fill(C.COST_YEARLY, { amount: dollars(r.yearly_cents) }));
  if (r.payee_name) parts.push(r.payee_name);
  return parts;
}

const which = (d: SetAsideDue) => (d.which === 'first' ? C.FIRST_INSTALLMENT : d.which === 'second' ? C.SECOND_INSTALLMENT : null);
/** A schedule row's second line. The server's signed days_until says how far each is from today. */
export function dueSub(d: SetAsideDue, asOf: string): string {
  const tail = which(d);
  const join = (...parts: (string | null)[]) => parts.filter(Boolean).join(' · ');
  switch (d.status) {
    case 'paid': return join(fill(C.PAID_ON_TIME, { date: dayLabel(d.paid_on!) }), tail);
    case 'late': return join(fill(C.PAID_ON_LATE, { date: dayLabel(d.paid_on!) }), d.days_late === 1 ? C.ONE_DAY_AFTER : fill(C.DAYS_AFTER, { n: d.days_late ?? 0 }), tail);
    case 'missed': return join(C.NOT_PAID, whenWords(d.days_until), tail);
    case 'skipped': return C.WAS_NOT_DUE;
    default: return join(cap(whenWords(d.days_until, d.due_on, asOf)), tail);
  }
}
export function paymentMeta(p: SetAsidePayment, oneOffName?: string): string {
  const to = oneOffName ? fill(C.MATCHED_TO_ONE_OFF, { name: oneOffName }) : fill(C.MATCHED_TO, { date: dayLabel(p.due_on) });
  const late = p.late && p.days_late > 0 ? `, ${p.days_late === 1 ? C.ONE_DAY_LATE : fill(C.DAYS_LATE, { n: p.days_late })}` : '';
  return `${dateText(p.posted_at)} · ${p.account_name} · ${label(p.category)} · ${to}${late}`;
}

/** The head's state line: the list's words, with the date on a short one, how long ago on an unpaid one and the next
 *  installment after a late payment. A paid one-off reads as replaced. */
export function headState(r: SetAsideDetail): { text: string; tone: Tone | 'done' } {
  if (r.paid) return { tone: 'done', text: fill(C.REPLACED, { date: dateText(r.paid.posted_at), amount: dollars(r.paid.cents), account: r.paid.account_name }) };
  const tone = stateTone(r.state);
  const account = accountWord(r);
  const withAccount = (text: string) => (account ? `${text} · ${account}` : text);
  if (r.state === 'not_paid') {
    const missed = r.dues.find((d) => d.due_on === r.missed_due);
    return { tone, text: withAccount(missed ? `${stateText(r)} · ${whenWords(missed.days_until)}` : stateText(r)) };
  }
  if (r.state === 'short' && r.next_due) return { tone, text: `Due ${dayLabel(r.next_due)}, ${stateLine(r).replace(/^Due /, '')}` };
  const late = r.state === 'on_track' && r.next_due ? [...r.dues].reverse().find((d) => d.status === 'late') : undefined;
  if (late && r.next_due) return { tone, text: fill(C.PAID_THEN_NEXT, { due: dayLabel(late.due_on), on: dayLabel(late.paid_on!), next: dateText(r.next_due) }) };
  return { tone, text: stateLine(r) };
}

const monthAfter = (iso: string) => monthNameOf((Number(iso.slice(5, 7)) % 12) + 1);
/** The Put away card (mockup, Put away): the shortfall first, then should-be as context. The figures are the server's. */
export function fundLines(r: SetAsideRow, asOf: string): { tone: Tone; lead: string; detail: string; context: string } {
  const monthly = dollars(r.monthly_cents);
  const from = r.counted_from ? monthAfter(r.counted_from) : monthName(r.first_month);
  const since = r.counted_from ? fill(C.SINCE_PAYMENT, { month: monthName(r.counted_from) }) : '';
  const context = r.should_cents > 0
    ? `${fill(C.SHOULD_CONTEXT, { should: dollars(r.should_cents), monthly, from, to: monthName(asOf) })}${since}`
    : fill(C.FROM_MONTH_BY, { monthly, from: monthName(r.first_month), amount: dollars(r.amount_cents), due: r.next_due ? dateText(r.next_due, true) : '' });
  const owed = fill(C.DUE_PUT, { due: dollars(r.installment_cents), put: dollars(r.put_away_cents) });
  if (r.state === 'short') return { tone: 'soon', lead: fill(C.SHORT_FOR, { amount: dollars(r.short_cents), date: dayLabel(r.next_due!) }), detail: owed, context };
  if (r.state === 'not_paid') return { tone: 'soon', lead: fill(C.NOT_PAID_YET, { date: r.missed_due ? dayLabel(r.missed_due) : '' }), detail: owed, context };
  if (r.state === 'behind') return { tone: 'behind', lead: `Behind by ${dollars(r.behind_cents)}`, detail: `${dollars(r.put_away_cents)} put away, ${dollars(r.should_cents)} should be by now`, context };
  return { tone: 'track', lead: C.ON_TRACK, detail: r.should_cents > 0 ? fill(C.SHOULD_BY_NOW, { should: dollars(r.should_cents) }) : C.NOTHING_SHOULD, context };
}
/** Under the fund card of an unpaid installment: the money stays, and should-be keeps counting. */
export function notPaidFund(r: SetAsideRow): string | null {
  return r.state === 'not_paid' && r.account && r.counted_from
    ? fill(C.NOT_PAID_FUND, { account: r.account.name, amount: dollars(r.installment_cents), month: monthName(r.counted_from) }) : null;
}

/** The offer to set aside for the next one, in the server's figures (replace_offer: year, cents, monthly_cents). */
export function replaceText(d: SetAsideDetail): string {
  const rp = d.replace!;
  const vars = { name: d.name, month: `${monthShort(rp.paid_on)} ${rp.paid_on.slice(0, 4)}`, paid: dollars(rp.paid_cents) };
  const o = d.replace_offer;
  return o ? fill(C.REPLACE_BODY, { ...vars, year: o.year, amount: dollars(o.cents), monthly: dollars(o.monthly_cents) }) : fill(C.REPLACE_NO_OFFER, vars);
}

/** Where "Find the payment" goes: Transactions on the range the server gives (find_from to find_to), narrowed to the
 *  payee when there is one. */
export function findHref(r: Pick<SetAsideDetail, 'find_from' | 'find_to' | 'payee_name'>): string {
  const q = new URLSearchParams({ dates: 'custom', ...(r.find_from && r.find_to ? { from: r.find_from, to: r.find_to } : {}) });
  if (r.payee_name) q.set('q', r.payee_name);
  return `/transactions?${q}`;
}

/** The estimate's evidence for one item: what the server has not checked, then the sources it did cite (lifespan, cost).
 *  An unchecked figure is said to need checking and its source is not shown, so it never reads as sourced. */
export function sourceNotes(e: Pick<SetAsideEstimate, 'to_check' | 'cost_to_check'> & { sources?: string[] }): string[] {
  const [life, cost] = e.sources ?? [];
  return [
    ...checkNotes(e).map(cap),
    ...(!e.to_check && life ? [fill(C.SOURCE_LIFESPAN, { source: life })] : []),
    ...(!e.cost_to_check && cost ? [fill(C.SOURCE_COST, { source: cost })] : []),
  ];
}

// ---- The form (Add and the Edit sheet) ----
export type Draft = {
  name: string; kind: SetAsideKind; amount: string; dueMonth: string; dueDay: string; secondMonth: string; secondDay: string; dueYear: string;
  accountId: string; payeeKey: string | null; payeeName: string | null; category: string | null; notes: string;
  item: string; installedYear: string; modelYear: string; miles: string;
};
export const emptyDraft = (asOf: string): Draft => ({ name: '', kind: 'yearly', amount: '', dueMonth: String(Number(asOf.slice(5, 7))), dueDay: '1', secondMonth: '', secondDay: '',
  dueYear: '', accountId: '', payeeKey: null, payeeName: null, category: null, notes: '', item: 'other', installedYear: '', modelYear: '', miles: '' });
export const draftFrom = (r: SetAsideRow): Draft => ({
  name: r.name, kind: r.kind, amount: dollarsText(r.amount_cents), dueMonth: String(r.due_month ?? ''), dueDay: String(r.due_day ?? 1), secondMonth: String(r.second_month ?? ''),
  secondDay: String(r.second_day ?? ''), dueYear: String(r.due_year ?? ''), accountId: r.account?.id ? String(r.account.id) : '', payeeKey: r.payee_key, payeeName: r.payee_name,
  category: r.category, notes: r.notes ?? '', item: r.estimate?.item ?? 'other', installedYear: String(r.estimate?.installed_year ?? ''), modelYear: String(r.estimate?.model_year ?? ''),
  miles: String(r.estimate?.miles ?? '') });

const int = (s: string) => (/^\d+$/.test(s.trim()) ? Number(s.trim()) : null);
const validDay = (m: number | null, day: number | null) => day !== null && day >= 1 && day <= 31 && !(m === 2 && day > 29);
/** Reads a draft into the body the server takes, refusing what the server would. `unchanged` is the draft it started
 *  from: a one-off's year left alone stays, even when it has gone by, and so does a month gone by this year when the
 *  year and month are both left alone (the server's rules). */
export function readDraft(d: Draft, asOf: string, unchanged?: Draft): { body: SetAsideBody } | { error: string; field: string } {
  const name = d.name.trim();
  if (!name || name.length > 120) return { error: C.BAD_NAME, field: 'name' };
  const cents = toHundredths(d.amount);
  if ('error' in cents || cents.value < 1 || cents.value > 100_000_000) return { error: C.BAD_AMOUNT, field: 'amount' };
  const body: SetAsideBody = { name, kind: d.kind, amount_cents: cents.value, due_month: null, due_day: null, second_month: null, second_day: null, due_year: null,
    account_id: d.accountId ? Number(d.accountId) : null, payee_key: d.payeeKey, category: d.category, estimate: null, notes: d.notes.trim() || null };
  const year = Number(asOf.slice(0, 4));
  if (d.kind === 'one_off') {
    const y = int(d.dueYear);
    const kept = unchanged?.kind === 'one_off' && unchanged.dueYear === d.dueYear;
    if (y === null || (!kept && (y < year || y > year + 60))) return { error: fill(C.BAD_YEAR, { lo: year, hi: year + 60 }), field: 'dueYear' };
    const month = int(d.dueMonth) ?? 12;
    if (month < 1 || month > 12) return { error: C.BAD_MONTH, field: 'dueMonth' };
    const sameDate = kept && (int(unchanged?.dueMonth ?? '') ?? 12) === month;
    if (y === year && month < Number(asOf.slice(5, 7)) && !sameDate) return { error: C.PAST_MONTH, field: 'dueMonth' };
    body.due_year = y;
    body.due_month = month;
    if (d.item !== 'other') {
      const installed = d.item === 'car' ? int(d.modelYear) : int(d.installedYear);
      if (installed === null || installed < 1950 || installed > year) return { error: C.BAD_INSTALLED, field: d.item === 'car' ? 'modelYear' : 'installedYear' };
      const miles = d.item === 'car' && d.miles.trim() ? int(d.miles.replace(/,/g, '')) : null;
      if (d.item === 'car' && d.miles.trim() && miles === null) return { error: C.BAD_MILES, field: 'miles' };
      body.estimate = { item: d.item, installed_year: d.item === 'car' ? null : installed, model_year: d.item === 'car' ? installed : null, miles };
    }
    return { body };
  }
  const m = int(d.dueMonth), day = int(d.dueDay);
  if (m === null || m < 1 || m > 12) return { error: C.BAD_MONTH, field: 'dueMonth' };
  if (!validDay(m, day)) return { error: C.BAD_DAY, field: 'dueDay' };
  body.due_month = m;
  body.due_day = day;
  if (d.kind === 'twice_yearly') {
    const m2 = int(d.secondMonth), day2 = int(d.secondDay);
    if (m2 === null || m2 < 1 || m2 > 12) return { error: C.BAD_MONTH, field: 'secondMonth' };
    if (!validDay(m2, day2)) return { error: C.BAD_DAY, field: 'secondDay' };
    if (m2 === m && day2 === day) return { error: C.SAME_DATES, field: 'secondMonth' };
    body.second_month = m2;
    body.second_day = day2;
  }
  return { body };
}

/** An edit sends only what changed (the PUT is partial). A change of kind sends all the due fields so the new kind's
 *  are set and the old kind's are cleared. The estimate's inputs go only when they changed, so the stored basis, and
 *  with it the ESTIMATE tag, is left to the server. */
export function changedBody(now: SetAsideBody, was: SetAsideBody): Partial<SetAsideBody> {
  const out: Record<string, unknown> = {};
  for (const k of ['name', 'kind', 'amount_cents', 'account_id', 'payee_key', 'category', 'notes'] as const) if (now[k] !== was[k]) out[k] = now[k];
  for (const k of ['due_month', 'due_day', 'second_month', 'second_day', 'due_year'] as const) if (now.kind !== was.kind || now[k] !== was[k]) out[k] = now[k];
  if (JSON.stringify(now.estimate) !== JSON.stringify(was.estimate)) out.estimate = now.estimate;
  return out as Partial<SetAsideBody>;
}

/** What the form asks POST /setasides/estimate: the draft as it will be saved (for an edit, only what changed, with the
 *  set-aside's id so the server fills in the rest), or null while it does not read. A new one-off with an item and
 *  an age asks even before its amount and year exist: the server's estimate supplies them. */
export function previewRequest(d: Draft, asOf: string, edit?: { id: number; was: SetAsideBody; initial: Draft }): PreviewIn | null {
  const read = readDraft({ ...d, name: d.name.trim() || d.item }, asOf, edit?.initial);
  const strip = (b: Partial<SetAsideBody>): PreviewIn => {
    const { name: _n, notes: _t, payee_key: _p, category: _c, account_id: _a, ...rest } = b;
    return rest;
  };
  if ('body' in read) {
    if (!edit) return strip(read.body);
    const changed = changedBody(read.body, edit.was);
    // New estimate inputs would otherwise default the amount and year: ask with the ones that will be saved.
    if (changed.estimate) Object.assign(changed, { amount_cents: read.body.amount_cents, due_year: read.body.due_year, due_month: read.body.due_month });
    return { ...strip(changed), set_aside_id: edit.id };
  }
  if (edit || d.kind !== 'one_off' || d.item === 'other') return null;
  const given = (d.item === 'car' ? d.modelYear : d.installedYear).trim();
  const age = /^\d{4}$/.test(given) ? Number(given) : null;
  if (age === null || !['amount', 'dueYear'].includes(read.field)) return null;
  const miles = d.item === 'car' && d.miles.trim() ? int(d.miles.replace(/,/g, '')) : null;
  const amount = toHundredths(d.amount);
  const year = int(d.dueYear);
  return { kind: 'one_off', estimate: { item: d.item, installed_year: d.item === 'car' ? null : age, model_year: d.item === 'car' ? age : null, miles },
    ...('value' in amount && amount.value > 0 ? { amount_cents: amount.value } : {}), ...(year !== null ? { due_year: year, due_month: int(d.dueMonth) ?? 12 } : {}) };
}

/** The server's preview under the form: when it starts, the monthly amount, how long it is spread over and, for an edit,
 *  what should be put away by now. */
export function previewLines(pv: EstimatePreview): { when: string; monthly: string; more: string[] } {
  const month = monthName(pv.first_month);
  const when = !pv.next_due ? fill(C.FROM_ONLY, { month })
    : fill(pv.kind === 'one_off' ? C.FROM_PLANNED : C.FROM_NEXT, { month, date: dateText(pv.next_due, pv.kind !== 'twice_yearly') });
  const more: string[] = [];
  if (pv.months !== null) more.push(pv.months === 1 ? C.SPREAD_OVER_ONE : fill(C.SPREAD_OVER, { n: pv.months }));
  if (pv.should_cents !== undefined) more.push(pv.should_cents > 0 ? fill(C.SHOULD_BY_NOW, { should: dollars(pv.should_cents) }) : cap(C.NOTHING_SHOULD));
  return { when, monthly: `${dollars(pv.monthly_cents)} ${C.A_MONTH}`, more };
}
/** A preview that carries an estimate (an item was sent) rather than just a draft's figures. */
export const hasEstimate = (pv: EstimatePreview): pv is EstimatePreview & EstimateOut => pv.item !== undefined && pv.range !== undefined;

/** The reasoning under the estimate (mockup, Add a set-aside), in the server's years and amounts. */
export function estimateWords(e: EstimateOut): string {
  const range = { lo: e.lifespan[0], hi: e.lifespan[1], from: e.range[0], to: e.range[1], planned: e.planned_year };
  if (e.item === 'car') {
    if (e.miles_per_year === null || e.lifespan_miles === null) return fill(C.EST_CAR_NO_MILES, { ...range, model: e.model_year! });
    const miles = { ...range, mlo: e.lifespan_miles[0].toLocaleString('en-US'), mhi: e.lifespan_miles[1].toLocaleString('en-US'), model: e.model_year!, mpy: e.miles_per_year.toLocaleString('en-US') };
    return fill(e.decided_by === 'age' ? C.EST_CAR_AGE : C.EST_CAR_MILES, miles);
  }
  const text = fill(C.EST_ITEM, { ...range, item: e.label.toLowerCase(), installed: e.installed_year!, amount: dollars(e.amount_cents), months: e.months, first: monthName(e.first_month) });
  return e.planned_year >= e.range[1] ? `${text} ${C.EST_PAST}` : text;
}
export { label };
