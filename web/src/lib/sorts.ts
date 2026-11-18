import { TEN_IN_A_ROW } from './copy';
import { dayOf } from './today';

/** Review focus P18: "Ten in a row" counts sorted cards this visit (not their matching rows), with no time window. An
 *  Undo, a Snooze or an Ignore breaks the run; it shows once per run. It replaces the sorting redesign's combos. The
 *  milestones at 100, 250, 500 and 1,000 sorted on this device stay. There are no streaks to lose. */
export const RUN_AT = 10;
export type Run = { n: number; shown: boolean };
export const NO_RUN: Run = { n: 0, shown: false };
export const MILESTONES = [100, 250, 500, 1000] as const;
const KEY = 'steward-sorts';

export function runAfter(run: Run, event: 'sort' | 'break'): { run: Run; label: string | null } {
  if (event === 'break') return { run: NO_RUN, label: null };
  const n = run.n + 1;
  const ten = n >= RUN_AT && !run.shown;
  return { run: { n, shown: run.shown || ten }, label: ten ? TEN_IN_A_ROW : null };
}

export type Tally = { total: number; day: string; today: number };
const count = (v: unknown) => (typeof v === 'number' && Number.isInteger(v) && v >= 0 ? v : 0);

export function readTally(now: Date = new Date()): Tally {
  let t: Partial<Record<keyof Tally, unknown>> = {};
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(KEY) ?? '{}');
    if (raw && typeof raw === 'object') t = raw as typeof t;
  } catch { /* unreadable: nothing yet */ }
  const day = dayOf(now);
  return { total: count(t.total), day, today: t.day === day ? count(t.today) : 0 };
}

/** n transactions sorted on this device (a sort counts itself and the matching rows it set). The milestone crossed,
 *  the highest if several are. */
export function addSorts(n: number, now: Date = new Date()): { tally: Tally; milestone: number | null } {
  const was = readTally(now);
  const tally = { total: was.total + n, day: was.day, today: was.today + n };
  try { localStorage.setItem(KEY, JSON.stringify(tally)); } catch { /* private mode: not kept */ }
  const crossed = MILESTONES.filter((m) => was.total < m && tally.total >= m);
  return { tally, milestone: crossed.length ? crossed[crossed.length - 1] : null };
}
