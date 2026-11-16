import { dollars } from './format';

/** A round step for an axis with about `intervals` gaps up to `max` (the Plan's band chart and Accounts' net worth). */
export function niceStep(max: number, intervals = 3): number {
  if (max <= 0) return 1;
  const raw = max / intervals;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const f = raw / pow;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 3 ? 3 : f <= 5 ? 5 : 10) * pow;
}

export function shortMoney(cents: number): string {
  const d = cents / 100;
  if (Math.abs(d) >= 1e6) return `$${+(d / 1e6).toFixed(1)}M`;
  if (Math.abs(d) >= 1e3) return `$${Math.round(d / 1e3)}k`;
  return `$${Math.round(d)}`;
}

export function millions(cents: number): string {
  return cents >= 100_000_000 ? `$${+(cents / 100_000_000).toFixed(1)} million` : dollars(cents);
}

/** At most `max` evenly spaced points, always keeping the first and last. */
export function thin<T>(values: T[], max: number): T[] {
  if (values.length <= max) return values;
  const step = Math.ceil(values.length / max);
  const out = values.filter((_, i) => i % step === 0);
  if (out[out.length - 1] !== values[values.length - 1]) out.push(values[values.length - 1]);
  return out;
}
