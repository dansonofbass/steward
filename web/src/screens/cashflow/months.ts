import type { FlowMonth } from '../../api/types';
import { FLOW_READOUT, MONTH_SO_FAR } from '../../lib/copy';
import { dollars } from '../../lib/format';

const SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const p2 = (n: number) => String(n).padStart(2, '0');

export const monthShort = (ym: string) => SHORT[Number(ym.slice(5, 7)) - 1];
/** The month's name alone: "2026-10" -> "October". */
export const monthName = (ym: string) => LONG[Number(ym.slice(5, 7)) - 1];
/** A month number (1-12) as its short and long name: "5" -> "May". */
export const monthShortOf = (month: number) => SHORT[month - 1];
export const monthNameOf = (month: number) => LONG[month - 1];
export const monthLong =(ym: string) => `${monthName(ym)} ${ym.slice(0, 4)}`;
export const isCurrent = (ym: string, asOf: string) => asOf.startsWith(ym);
/** A month in progress is "<Month> <Year> so far" (design-pass copy rule). */
export const monthTitle = (ym: string, asOf: string) => (isCurrent(ym, asOf) ? MONTH_SO_FAR.replace('{month}', monthLong(ym)) : monthLong(ym));

/** The whole month, or the month so far when it is the current one. */
export function monthRange(ym: string, asOf: string): { from: string; to: string } {
  const [y, m] = ym.split('-').map(Number);
  const last = new Date(y, m, 0).getDate();
  return { from: `${ym}-01`, to: isCurrent(ym, asOf) ? asOf : `${ym}-${p2(last)}` };
}

export function drillHref(ym: string, category: string, asOf: string): string {
  const { from, to } = monthRange(ym, asOf);
  return `/transactions?${new URLSearchParams({ category, dates: 'custom', from, to })}`;
}

export const STRIP_W = 300;
export const STRIP_H = 44;
export type StripBar = { x: number; y: number; w: number; h: number; cls: string };
const r1 = (n: number) => Math.round(n * 10) / 10;

/** Home's strip (design decision 1): one bar per month for the difference, above or below one line. */
export function stripBars(months: FlowMonth[], asOf: string): { axis: number; bars: StripBar[] } {
  const pad = 2;
  const usable = STRIP_H - pad * 2;
  const up = Math.max(0, ...months.map((m) => m.net_cents));
  const down = Math.max(0, ...months.map((m) => -m.net_cents));
  const total = up + down;
  const axis = total === 0 ? STRIP_H / 2 : pad + (up / total) * usable;
  const slot = STRIP_W / months.length;
  const bars = months.map((m, i) => {
    const h = total === 0 ? 2 : Math.max(2, (Math.abs(m.net_cents) / total) * usable);
    const below = m.net_cents < 0;
    return {
      x: r1(i * slot + 3.5), y: r1(below ? axis : axis - h), w: r1(slot - 7), h: r1(h),
      cls: [below ? 'out' : 'in', isCurrent(m.month, asOf) ? 'so-far' : ''].filter(Boolean).join(' '),
    };
  });
  return { axis: r1(axis), bars };
}

/** Home's hover readout (sorting redesign, Home): "September: Income $8,200 · Spending $6,900 · +$1,300"; the
 *  current month is "so far". */
export function monthReadout(m: FlowMonth, asOf: string): string {
  const name = isCurrent(m.month, asOf) ? MONTH_SO_FAR.replace('{month}', monthName(m.month)) : monthName(m.month);
  return FLOW_READOUT.replace('{month}', name).replace('{in}', dollars(m.in_cents)).replace('{out}', dollars(m.out_cents))
    .replace('{net}', dollars(m.net_cents, { sign: 'always' }));
}
