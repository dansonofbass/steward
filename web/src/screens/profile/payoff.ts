import { today } from '../../lib/today';

// The mortgage payoff date from balance, rate and monthly principal and interest (carried decision; ruling 9).
export type Month = { year: number; month: number };   // month is 1-12
export type Payoff = { kind: 'paid_off' } | { kind: 'never' } | { kind: 'months'; payments: number; year: number; month: number };

/**
 * When a fixed-payment loan is paid off. Balance is what is owed, in cents (positive); the annual rate is in
 * thousandths of a percent (2.875% -> 2875); the payment is the monthly principal and interest in cents.
 * The first payment is next month, so the last one is `payments` months after `from`.
 */
export function payoff(balanceCents: number, rateMilli: number, paymentCents: number, from: Month): Payoff {
  if (balanceCents <= 0) return { kind: 'paid_off' };
  if (paymentCents <= 0) return { kind: 'never' };
  let payments: number;
  if (rateMilli === 0) {
    payments = Math.ceil(balanceCents / paymentCents);
  } else {
    const r = rateMilli / 100_000 / 12;
    const interest = balanceCents * r;
    if (paymentCents <= interest) return { kind: 'never' };
    // n = -ln(1 - B·r / P) / ln(1 + r); the small nudge keeps an exact whole number from rounding up.
    payments = Math.ceil(-Math.log(1 - interest / paymentCents) / Math.log(1 + r) - 1e-9);
  }
  const index = from.year * 12 + (from.month - 1) + payments;
  return { kind: 'months', payments, year: Math.floor(index / 12), month: (index % 12) + 1 };
}

export const payoffYmd = (m: Month): string => `${m.year}-${String(m.month).padStart(2, '0')}-01`;
export const thisMonth = (d: Date = new Date()): Month => { const t = today(d); return { year: Number(t.slice(0, 4)), month: Number(t.slice(5, 7)) }; };
/** The month of an ISO date or year-month, like "2026-10-14" or "2026-10". */
export const monthOf = (iso: string): Month => ({ year: Number(iso.slice(0, 4)), month: Number(iso.slice(5, 7)) });
/** Whole months from a to b ("2026-10" to "2026-12" is 2). */
export const monthsBetween = (a: string, b: string): number => {
  const [x, y] = [monthOf(a), monthOf(b)];
  return (y.year - x.year) * 12 + (y.month - x.month);
};
