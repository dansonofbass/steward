const MINUS = '−';
const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 });
const compactUsd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 2 });
const wholeUsd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

export type MoneyOpts = { sign?: 'auto' | 'always' | 'never'; compact?: boolean };

export function money(cents: number, opts: MoneyOpts = {}): string {
  const abs = Math.abs(cents);
  let body: string;
  if (opts.compact && abs >= 1_000_000_00) body = compactUsd.format(abs / 100); // $1.26M
  else if (opts.compact && abs >= 1_000_00) body = wholeUsd.format(Math.round(abs / 100)); // $9,500 (whole dollars from $1,000 up)
  else body = usd.format(abs / 100);
  const sign = opts.sign === 'never' ? '' : cents < 0 ? MINUS : opts.sign === 'always' && cents > 0 ? '+' : '';
  return sign + body;
}

export function moneyParts(cents: number): { sign: '' | '−' | '+'; dollars: string; cents: string } {
  const abs = Math.abs(cents);
  const dollars = groupedWhole.format(Math.floor(abs / 100));
  return { sign: cents < 0 ? MINUS : '', dollars, cents: String(abs % 100).padStart(2, '0') };
}

// Built once: toLocaleDateString with options builds a new Intl.DateTimeFormat on every call, and a Review list renders
// one date per card (three sorts in a row under a 4x CPU throttle went over the 100 ms long-task budget on it).
const shortDay = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' });
const shortDayYear = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
const shortMonthYear = new Intl.DateTimeFormat('en-US', { month: 'short', year: 'numeric' });
const longMonthYear = new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric' });
const groupedWhole = new Intl.NumberFormat('en-US');

const dayMs = 86_400_000;
function localDate(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d);
}
function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

export function relativeDays(iso: string | null | undefined, today: Date): string {
  if (!iso) return 'Not yet';
  const n = Math.round((startOfDay(today).getTime() - localDate(iso).getTime()) / dayMs);
  if (n <= 0) return 'Today';
  if (n === 1) return 'Yesterday';
  return `${n} days ago`;
}

export function dateLabel(iso: string, today: Date): string {
  const d = localDate(iso);
  const sameYear = d.getFullYear() === today.getFullYear();
  return (sameYear ? shortDay : shortDayYear).format(d);
}

/** "Jun 2027", from a year and a 1-based month. */
export function monthYear(year: number, month: number): string {
  return shortMonthYear.format(new Date(year, month - 1, 1));
}

export function monthLabel(iso: string): string {
  return longMonthYear.format(localDate(iso));
}

/** The viewer's local calendar day (YYYY-MM-DD) for a full timestamp, so a UTC time late or early in the day lands on the right date. */
export function localYmd(iso: string): string {
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export function dateLabelFromIso(iso: string, today: Date): string {
  return dateLabel(localYmd(iso), today);
}

/** Whole dollars, no cents: 476012 -> "$4,760", -9950 -> "−$100". */
export function dollars(cents: number, opts: { sign?: 'auto' | 'always' } = {}): string {
  const whole = Math.round(Math.abs(cents) / 100);
  const sign = cents < 0 && whole > 0 ? MINUS : opts.sign === 'always' && cents > 0 ? '+' : '';
  return sign + wholeUsd.format(whole);
}
