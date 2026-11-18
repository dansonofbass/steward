import { addDays, dayOf } from '../../lib/today';

/** The Dates filter. The URL carries `dates=7|30|month|all|custom` (7 when absent); `from`/`to` appear only for custom. */
export type DatesMode = '7' | '30' | 'month' | 'all' | 'custom';
export const DATES_MODES: DatesMode[] = ['7', '30', 'month', 'all', 'custom'];
export type Range = { from?: string; to?: string };

/** The household's calendar day as YYYY-MM-DD (issue #26). */
export function ymd(d: Date): string {
  return dayOf(d);
}

export function parseMode(raw: string | null): DatesMode {
  return DATES_MODES.includes(raw as DatesMode) ? (raw as DatesMode) : '7';
}

/** The from/to sent to the API for a mode, counted in the household's days (issue #26). Custom takes the URL's own from/to. */
export function rangeFor(mode: DatesMode, today: Date, custom: Range = {}): Range {
  const to = dayOf(today);
  switch (mode) {
    case '7': return { from: addDays(to, -6), to };
    case '30': return { from: addDays(to, -29), to };
    case 'month': return { from: `${to.slice(0, 8)}01`, to };
    case 'all': return {};
    case 'custom': return { from: custom.from || undefined, to: custom.to || undefined };
  }
}
