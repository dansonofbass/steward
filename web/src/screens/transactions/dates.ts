/** The Dates filter. The URL carries `dates=7|30|month|all|custom` (7 when absent); `from`/`to` appear only for custom. */
export type DatesMode = '7' | '30' | 'month' | 'all' | 'custom';
export const DATES_MODES: DatesMode[] = ['7', '30', 'month', 'all', 'custom'];
export type Range = { from?: string; to?: string };

const p = (n: number) => String(n).padStart(2, '0');

/** A local calendar day as YYYY-MM-DD. */
export function ymd(d: Date): string {
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function daysBefore(today: Date, n: number): Date {
  return new Date(today.getFullYear(), today.getMonth(), today.getDate() - n);
}

export function parseMode(raw: string | null): DatesMode {
  return DATES_MODES.includes(raw as DatesMode) ? (raw as DatesMode) : '7';
}

/** The from/to the API gets for a mode, computed in local time. Custom takes the URL's own from/to. */
export function rangeFor(mode: DatesMode, today: Date, custom: Range = {}): Range {
  switch (mode) {
    case '7': return { from: ymd(daysBefore(today, 6)), to: ymd(today) };
    case '30': return { from: ymd(daysBefore(today, 29)), to: ymd(today) };
    case 'month': return { from: ymd(new Date(today.getFullYear(), today.getMonth(), 1)), to: ymd(today) };
    case 'all': return {};
    case 'custom': return { from: custom.from || undefined, to: custom.to || undefined };
  }
}
