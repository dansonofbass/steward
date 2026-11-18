// Issue #26: "today" is the household's, not the device's. The server works in the household's time zone
// (src/steward/clock.py) and GET /api/auth/me says which; RequireAuth hands it here before any screen renders, as it
// does the gateway's name. Every date default and every relative label ("Today", "Yesterday", "3 days ago") asks
// here, so a member travelling in another zone, or anyone near midnight, sees the household's day. Before sign-in,
// and in tests, there is no zone and the device's own is used.

let zone: string | undefined;
let parts = formatter(undefined);
let clock = clockFormatter(undefined);
// One instant at a time is asked again and again (a Review list asks per card), so the last answer is kept.
let lastAt = NaN;
let lastDay = '';

function formatter(timeZone: string | undefined): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat('en-US', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' });
}
function clockFormatter(timeZone: string | undefined): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat('en-US', { timeZone, hour: 'numeric', minute: '2-digit', hourCycle: 'h12' });
}

/** The household's zone from /me. A name the browser doesn't know (or none) leaves the device's zone. */
export function setHouseholdZone(next: string | null | undefined): void {
  const name = next?.trim() || undefined;
  if (name === zone) return;
  try {
    parts = formatter(name);
    clock = clockFormatter(name);
    zone = name;
  } catch {
    parts = formatter(undefined);
    clock = clockFormatter(undefined);
    zone = undefined;
  }
  lastAt = NaN;
}
export function forgetHouseholdZone(): void { setHouseholdZone(undefined); }
export const householdZone = (): string | undefined => zone;

const instant = (at: Date | number | string): number => (at instanceof Date ? at.getTime() : typeof at === 'number' ? at : Date.parse(at));

/** The household's calendar day (YYYY-MM-DD) at an instant: a Date, epoch milliseconds or a full ISO timestamp. An
 *  instant that can't be read (an empty or malformed timestamp) is '', never a RangeError from Intl mid-render. */
export function dayOf(at: Date | number | string): string {
  const t = instant(at);
  if (!Number.isFinite(t)) return '';
  if (t === lastAt) return lastDay;
  const p: Record<string, string> = {};
  for (const { type, value } of parts.formatToParts(t)) p[type] = value;
  lastAt = t;
  lastDay = `${p.year}-${p.month}-${p.day}`;
  return lastDay;
}

/** The household's today, YYYY-MM-DD. */
export const today = (now: Date = new Date()): string => dayOf(now);

/** The household's year today. */
export const thisYear = (now: Date = new Date()): number => Number(today(now).slice(0, 4));

/** A YYYY-MM-DD day moved by n days (calendar days, so a clock change never skips or repeats one). */
export function addDays(ymd: string, n: number): string {
  const [y, m, d] = ymd.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

/** Whole days from one YYYY-MM-DD day to another (positive when `to` is later). */
export function daysBetween(from: string, to: string): number {
  const utc = (s: string) => { const [y, m, d] = s.split('-').map(Number); return Date.UTC(y, m - 1, d); };
  return Math.round((utc(to) - utc(from)) / 86_400_000);
}

/** "6:10 AM" on the household's clock, with a plain space (the browser's own format puts a narrow one before AM); ''
 *  for an instant that can't be read. */
export function clockTime(at: Date | number | string): string {
  const t = instant(at);
  if (!Number.isFinite(t)) return '';
  return clock.format(t).replace(/\s/g, ' ');
}
