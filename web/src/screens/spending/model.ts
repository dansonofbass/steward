import type {
  EverydayRow, FixedRow, SpendingKind, SpendingMonth, SpendingTargets, TargetChange, TargetRow, TargetsBody, TrendRow,
} from '../../api/types';
import { CATEGORY_ORDER, label } from '../../lib/categories';
import { dollars, money } from '../../lib/format';
import { monthName, monthShort } from '../cashflow/months';
import { dollarsText, toHundredths } from '../settings/money';
import * as C from './copy';
import { dayLabel, fill, joinNames } from './format';

export { dayLabel, fill, joinNames };
import { paidLine, setAsideHeadPart } from './setasides/model';


export const NOT_SPENDING = new Set(['income', 'business_income', 'interest', 'transfer', 'uncategorized']);
/** The categories Spending tracks, in the fixed category list's order (the service's SPENDING_CATEGORIES). */
export const SPENDING_KEYS = CATEGORY_ORDER.filter((c) => !NOT_SPENDING.has(c));

export function ordinal(n: number): string {
  const t = n % 100;
  const s = t >= 11 && t <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th';
  return `${n}${s}`;
}
export function shiftMonth(ym: string, by: number): string {
  const [y, m] = ym.split('-').map(Number);
  const i = y * 12 + (m - 1) + by;
  return `${Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, '0')}`;
}
export const monthOnly = monthName;
export const monthInitial = (ym: string) => monthShort(ym)[0];
export const daysLeftText = (n: number) => (n <= 0 ? C.LAST_DAY : n === 1 ? C.ONE_DAY_LEFT : fill(C.DAYS_LEFT, { n }));

/** A closed month's Flexible row this far under its target shows "{amount} to spare" (P14). */
export const SPARE_MIN_CENTS = 500;
export type Tone = 'track' | 'little' | 'clear' | 'spare' | 'none';
export const spareCents = (r: EverydayRow): number | null =>
  r.target_cents !== null && r.target_cents - r.spent_cents >= SPARE_MIN_CENTS ? r.target_cents - r.spent_cents : null;
/** The row's colour (P18): clearly over fills amber, a little over ink, on target muted; to spare is soft green text. */
export function paceTone(r: EverydayRow, current: boolean): Tone {
  if (r.state === 'none') return 'none';
  if (r.over_level === 'clear' || r.over_level === 'little') return r.over_level;
  return !current && spareCents(r) !== null ? 'spare' : 'track';
}

export function paceText(r: EverydayRow, current: boolean): string {
  switch (r.state) {
    case 'over': return fill(C.OVER_BY, { amount: dollars(r.over_cents ?? r.spent_cents - (r.target_cents ?? 0)) });
    case 'none': return r.typical_cents ? fill(C.NO_TARGET_TYPICAL, { amount: dollars(r.typical_cents) }) : C.NO_TARGET;
    default: {
      const spare = current ? null : spareCents(r);
      return spare !== null ? fill(C.TO_SPARE, { amount: dollars(spare) }) : current ? C.ON_TRACK : C.WITHIN;
    }
  }
}

/** The loose scale an untargeted row's bar is drawn on: the month's biggest everyday figure. */
export const paceScale = (m: SpendingMonth) => Math.max(0, m.not_sorted.cents, ...m.everyday.map((r) => Math.max(r.spent_cents, r.typical_cents ?? 0)));
export function fillPct(spent: number, target: number | null, scale: number): number {
  if (target !== null) return target === 0 ? (spent > 0 ? 100 : 0) : Math.min(100, Math.round((spent / target) * 100));
  return scale > 0 ? Math.min(100, Math.round((spent / scale) * 100)) : 0;
}
export const todayPct = (m: SpendingMonth) => (m.current && m.day !== null ? Math.round((m.day / m.days) * 100) : null);
export const unsortedText = (n: number) => (n === 1 ? C.UNSORTED_ONE : fill(C.UNSORTED_N, { n }));

export const isWatched = (k: SpendingKind) => k === 'fixed' || k === 'commitment';

/** A Bill's or a Commitment's sub-line (spec, Cases and copy), from the server's state. A new payee joins with " · "
 *  (P8). A Commitment over usual reads the figures, never "more": Steward never says what giving should be. */
export function fixedText(r: FixedRow): string {
  const day = r.typical_day ? ordinal(r.typical_day) : null;
  const usual = dollars(r.usual_cents ?? 0);
  const spent = dollars(r.spent_cents);
  let text: string;
  switch (r.state) {
    case 'waiting': text = day ? fill(C.WAITING, { day }) : C.NOT_SEEN; break;
    case 'late': text = day ? fill(C.LATE, { day }) : C.NOT_SEEN; break;
    case 'so_far': text = fill(C.SO_FAR_USUAL, { spent, usual }); break;
    case 'under': text = fill(C.SPENT_USUAL, { spent, usual }); break;
    case 'over': text = r.kind === 'fixed' ? fill(C.MORE_THAN_USUAL, { amount: dollars(r.spent_cents - (r.usual_cents ?? 0)) }) : fill(C.SPENT_USUAL, { spent, usual }); break;
    case 'none': text = C.NOTHING_CAME_OUT; break;
    default: {
      const date = r.came_out_on ? dayLabel(r.came_out_on) : '';
      text = r.merchant ? fill(C.CAME_OUT_FROM, { merchant: r.merchant, date }) : fill(C.CAME_OUT, { date });
    }
  }
  return r.new_payee ? `${text} · ${fill(C.NEW_PAYEE, { name: r.new_payee.name, amount: money(r.new_payee.cents) })}` : text;
}

/** The row's amount: what came out, or what's expected while waiting or late; nothing for a closed month with none. */
export function fixedAmount(r: FixedRow): number | null {
  if (r.state === 'waiting' || r.state === 'late') return r.expected_cents;
  return r.state === 'none' ? null : r.spent_cents;
}

export function fixedPart(m: SpendingMonth): string | null {
  const h = m.head;
  const spent = dollars(h.fixed_spent_cents);
  switch (h.fixed_summary) {
    // Ruling 19: nothing to judge them by, but the head never hides real money.
    case 'none': return m.fixed.length > 0 ? fill(C.FIXED_SPENT, { spent }) : null;
    case 'to_come': return fill(C.FIXED_TO_COME, { spent, n: h.fixed_not_yet });
    case 'more': return fill(C.FIXED_MORE, { spent, amount: dollars(h.fixed_more_cents) });
    default: return fill(C.FIXED_SPENT, { spent });
  }
}

/** Ruling 26: the month is judged against the plan only when it has an everyday target. Without one the plan would be
 *  the fixed costs alone, and everyday spending, which has no target to keep to, would read as going over it. */
const hasEverydayTarget = (m: SpendingMonth) => m.head.everyday_target_cents > 0;

/** The month's one figure: "$7,974 of $8,140", or "$7,974 spent" with no everyday target. */
export function headFigure(m: SpendingMonth): { amount: string; tail: string } {
  const h = m.head;
  return { amount: dollars(h.spent_cents), tail: hasEverydayTarget(m) ? fill(C.OF, { amount: dollars(h.planned_cents) }) : C.SPENT_WORD };
}

/** The line under the month's figure: days left (a finished month: over, under or on the plan, and nothing without an
 *  everyday target), Everyday, Fixed costs. */
export function headParts(m: SpendingMonth): string[] {
  const h = m.head;
  const parts: string[] = [];
  if (m.current) parts.push(daysLeftText(m.days_left ?? 0));
  else if (hasEverydayTarget(m)) {
    const diff = h.spent_cents - h.planned_cents;
    parts.push(diff === 0 ? C.ON_PLAN : fill(diff > 0 ? C.OVER_TOTAL : C.UNDER_TOTAL, { amount: dollars(Math.abs(diff)) }));
  }
  parts.push(hasEverydayTarget(m)
    ? fill(C.FLEXIBLE_OF, { spent: dollars(h.everyday_spent_cents), target: dollars(h.everyday_target_cents) })
    : fill(C.FLEXIBLE_SPENT, { spent: dollars(h.everyday_spent_cents) }));
  const f = fixedPart(m);
  if (f) parts.push(f);
  if (m.set_aside && m.set_aside.monthly_cents > 0) parts.push(setAsideHeadPart(m.set_aside));
  return parts;
}

/** Decision 16: the line under the figure in a month with a payment matched to a set-aside (built from the server's
 *  paid rows; the web adds nothing up that the head did not already count). */
export function setAsideLine(m: SpendingMonth): string | null {
  return m.set_aside ? paidLine(m.set_aside) : null;
}

/** The month's money out and money in, Home's figure's two sides, as one quiet line; none when neither moved. */
export function inOutLine(m: SpendingMonth): string | null {
  const h = m.head;
  if (h.money_out_cents === 0 && h.money_in_cents === 0) return null;
  return fill(C.IN_OUT, { out: dollars(h.money_out_cents), in: dollars(h.money_in_cents) });
}

/** Decision 17: one line under the plan figure in a month a payment came out once in a while. */
export function occasionalLine(m: SpendingMonth): string | null {
  if (m.occasional.length === 0) return null;
  const amount = dollars(m.head.occasional_cents);
  return m.occasional.length === 1 ? fill(C.OCCASIONAL_ONE, { amount, label: label(m.occasional[0].category) }) : fill(C.OCCASIONAL_MANY, { amount });
}

export function overInText(r: TrendRow): { text: string; strong: boolean } {
  if (r.kind !== 'everyday') return { text: r.expected_cents !== null ? fill(C.EXPECTED, { amount: dollars(r.expected_cents) }) : '', strong: false };
  if (r.target_cents === null) return { text: C.NO_TARGET, strong: false };
  if (r.over_of === 0) return { text: '', strong: false };
  if (r.over_in === 0) return { text: r.over_of === 1 ? C.UNDER_ONE : fill(C.UNDER_ALL, { m: r.over_of }), strong: false };
  return { text: r.over_of === 1 ? C.OVER_IN_ONE : fill(C.OVER_IN, { n: r.over_in, m: r.over_of }), strong: r.over_in >= 3 };
}
export function trendSub(r: TrendRow): string {
  const typical = r.typical_cents !== null ? dollars(r.typical_cents) : null;
  if (r.kind === 'everyday' && r.target_cents !== null) {
    return typical ? fill(C.TARGET_TYPICAL, { target: dollars(r.target_cents), typical }) : fill(C.TARGET_ONLY, { target: dollars(r.target_cents) });
  }
  return typical ? fill(C.TYPICAL_ONLY, { typical }) : '';
}
export function steadyLine(rows: TrendRow[]): string | null {
  const names = rows.filter((r) => r.group === 'steady').map((r) => label(r.category));
  if (names.length === 0) return null;
  return fill(names.length === 1 ? C.STEADY_ONE : C.STEADY_MANY, { names: joinNames(names) });
}

// ---- Set targets: a draft of text fields, read back into the PUT body ----
export type DraftRow = { kind: SpendingKind; text: string };
export type Draft = { rows: Record<string, DraftRow> };
export type ReadDraft = { body: TargetsBody; changed: TargetChange[] } | { error: string; category: string | null };

/** A saved amount as its field's text; no amount is an empty field. */
const fieldText = (c: number | null) => (c === null ? '' : dollarsText(c));
export function draftFrom(t: SpendingTargets): Draft {
  return { rows: Object.fromEntries(t.categories.map((r) => [r.category, { kind: r.kind, text: fieldText(r.monthly_cents) }])) };
}
// The server's bounds (services/spending.py parse_targets), checked here so its 422 is only a backstop (ruling 25).
const MAX_TARGET_CENTS = 100_000_000;
type Read = { value: number } | { error: string };
const within = (p: Read, max: number, error: string): Read => ('error' in p ? p : p.value < 0 || p.value > max ? { error } : p);

/** A row's amount: none for a blank field (ruling 21: "0" is a target of $0) or a once-in-a-while row, whatever its
 *  field holds (the server refuses one). */
function rowCents(row: DraftRow): { value: number | null } | { error: string } {
  if (row.kind === 'occasional' || row.text.trim() === '') return { value: null };
  return within(toHundredths(row.text), MAX_TARGET_CENTS, C.BAD_TARGET_INPUT);
}

/** Whether a row differs from what is saved: its kind, or the amount its text reads as ("1,300.00" is no change). */
export function rowChanged(r: TargetRow, row: DraftRow): boolean {
  const c = rowCents(row);
  return row.kind !== r.kind || 'error' in c || c.value !== r.monthly_cents;
}
/** Every field that can't be saved, by category. */
export function draftErrors(t: SpendingTargets, d: Draft): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const r of t.categories) {
    const c = d.rows[r.category] ? rowCents(d.rows[r.category]) : null;
    if (c && 'error' in c) errors[r.category] = c.error;
  }
  return errors;
}
/** The changed rows (kind or amount), in the page's order; or the first value that can't be read. */
export function readDraft(t: SpendingTargets, d: Draft): ReadDraft {
  const changed: TargetChange[] = [];
  for (const r of t.categories) {
    const row = d.rows[r.category];
    if (!row) continue;
    const c = rowCents(row);
    if ('error' in c) return { error: c.error, category: r.category };
    if (row.kind !== r.kind || c.value !== r.monthly_cents) changed.push({ category: r.category, kind: row.kind, monthly_cents: c.value });
  }
  return { body: { targets: changed }, changed };
}
/** An amount as the server's event line writes it: whole dollars, or with its cents when it has some ("$470.50"). */
export const exact = (c: number) => (c % 100 === 0 ? dollars(c) : money(c));
const amountWord = (c: number | null, kind: SpendingKind) => (c !== null ? exact(c) : isWatched(kind) ? C.TYPICAL_WORD : C.NO_TARGET_WORD);
/** The save bar's summary. Each row reads as the server's event line does (services/spending.py _phrase, ruling 4):
 *  "Giving commitment → bill", with the amounts only when either side has one. */
export function changeSummary(t: SpendingTargets, p: Extract<ReadDraft, { body: TargetsBody }>): string {
  const by = new Map(t.categories.map((r) => [r.category, r]));
  return p.changed.map((c) => {
    const was = by.get(c.category)!;
    const bits: string[] = [];
    if (c.kind !== was.kind) bits.push(`${C.KIND_WORDS[was.kind]} → ${C.KIND_WORDS[c.kind]}`);
    if (c.monthly_cents !== was.monthly_cents) bits.push(`${amountWord(was.monthly_cents, was.kind)} → ${amountWord(c.monthly_cents, c.kind)}`);
    return `${label(c.category)} ${bits.join(', ')}`;
  }).join(' · ');
}
/** Whether there is a suggestion to offer: a book with no history yet has none. */
export const hasSuggestions = (t: SpendingTargets) => t.categories.some((r) => r.kind === 'everyday' && r.suggested_cents !== null);
export function acceptAll(t: SpendingTargets, d: Draft): Draft {
  const rows = { ...d.rows };
  for (const r of t.categories) {
    if (rows[r.category]?.kind === 'everyday' && r.suggested_cents !== null) rows[r.category] = { ...rows[r.category], text: dollarsText(r.suggested_cents) };
  }
  return { ...d, rows };
}
export function totals(t: SpendingTargets, d: Draft): { everyday: number; fixed: number; month: number; income: number | null; leaves: number | null } {
  let everyday = 0;
  let fixed = 0;
  for (const r of t.categories) {
    const row = d.rows[r.category];
    if (!row) continue;
    // An amount it can't save (unreadable or out of range) adds up as what is saved, until it is fixed.
    const c = rowCents(row);
    const cents = 'error' in c ? r.monthly_cents : c.value;
    if (row.kind === 'everyday') everyday += cents ?? 0;
    if (isWatched(row.kind)) fixed += cents ?? r.usual_cents ?? 0;
  }
  const month = everyday + fixed;
  const income = t.typical_income_cents;
  return { everyday, fixed, month, income, leaves: income === null ? null : income - month };
}
export function everydayTypicalText(r: TargetRow): string {
  if (r.typical_cents === null) return C.NO_TYPICAL;
  return r.typical_cents === 0 ? C.NOTHING_MOST_MONTHS : fill(C.TYPICAL_MONTH, { amount: dollars(r.typical_cents) });
}
export function fixedTypicalText(r: TargetRow): string {
  if (r.usual_cents === null || r.low_cents === null || r.high_cents === null) return C.NO_TYPICAL;
  if (r.low_cents === r.high_cents) return C.SAME_EVERY_MONTH;
  return fill(C.ABOUT_RANGE, { typical: dollars(r.usual_cents), low: dollars(r.low_cents), high: dollars(r.high_cents) });
}
