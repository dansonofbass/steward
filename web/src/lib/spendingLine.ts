import type { EverydayRow } from '../api/types';
import { label } from './categories';
import { OVER_FEW, OVER_MANY, OVER_NONE, OVER_ONE_CLEAR, OVER_ONE_LITTLE, SEE_ALL, SEE_NAME } from './copy';
import { dollars } from './format';

/** The most categories the line names one by one; from 4 it sums them up. */
const MAX_NAMED = 3;
/** The server already counts a little over as on target on days 1-7; the line reads the same rule from the month. */
const EARLY_DAYS = 7;

const fill = (s: string, vars: Record<string, string | number>) => s.replace(/\{(\w+)\}/g, (_, k: string) => String(vars[k]));

export type LineBit = { text: string; to?: string };
export type OverLine = { tone: 'quiet' | 'muted' | 'amber'; bits: LineBit[] };

/** What the over line reads (P26): Spending's month, or Home's narrowed one (its Flexible sign's over rows). */
export type OverRow = Pick<EverydayRow, 'category' | 'spent_cents' | 'target_cents' | 'over_cents' | 'over_level'>;
export type OverInput = { month: string; current: boolean; day: number | null; head: { everyday_target_cents: number }; everyday: OverRow[] };

const href = (r: OverRow, month: string) => `/spending/${r.category}?month=${month}`;

/** The over-target line (decision 2, P15, P16): the Flexible rows a little or clearly over, by dollars over, largest
 *  first, ties in Spending's order. Amber when any is clearly over, muted otherwise, and a quiet line when none is.
 *  None at all without a Flexible target (ruling 26). Home shows it for the current month; Spending for any month. */
export function overLine(m: OverInput | undefined): OverLine | null {
  if (!m || m.head.everyday_target_cents === 0) return null;
  const early = m.current && m.day !== null && m.day <= EARLY_DAYS;
  const counted = (r: OverRow) => r.over_level === 'clear' || (r.over_level === 'little' && !early);
  const over = m.everyday.map((r, i) => ({ r, i })).filter(({ r }) => counted(r))
    .sort((a, b) => (b.r.over_cents ?? 0) - (a.r.over_cents ?? 0) || a.i - b.i).map(({ r }) => r);
  if (over.length === 0) return { tone: 'quiet', bits: [{ text: OVER_NONE }] };
  const tone = over.some((r) => r.over_level === 'clear') ? 'amber' : 'muted';
  const cents = (r: OverRow) => dollars(r.over_cents ?? 0);
  if (over.length === 1) {
    const r = over[0];
    const name = label(r.category);
    const text = r.over_level === 'clear'
      ? fill(OVER_ONE_CLEAR, { name, amount: cents(r) })
      : fill(OVER_ONE_LITTLE, { name, spent: dollars(r.spent_cents), target: dollars(r.target_cents ?? 0) });
    return { tone, bits: [{ text }, { text: ' · ' }, { text: fill(SEE_NAME, { name }), to: href(r, m.month) }] };
  }
  if (over.length <= MAX_NAMED) {
    const bits: LineBit[] = [{ text: fill(OVER_FEW, { n: over.length }) }];
    over.forEach((r, i) => {
      if (i > 0) bits.push({ text: ' · ' });
      bits.push({ text: label(r.category), to: href(r, m.month) }, { text: ` ${cents(r)}` });
    });
    return { tone, bits };
  }
  const total = over.reduce((n, r) => n + (r.over_cents ?? 0), 0);
  return {
    tone,
    bits: [
      { text: fill(OVER_MANY, { n: over.length, total: dollars(total), name: label(over[0].category), amount: cents(over[0]) }) },
      { text: ' ' },
      { text: fill(SEE_ALL, { n: over.length }), to: `/spending?month=${m.month}#flexible` },
    ],
  };
}
