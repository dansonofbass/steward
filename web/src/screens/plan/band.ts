import { millions, niceStep, shortMoney } from '../../lib/chartScale';
import type { BandPoint } from './api';

export { millions, niceStep, shortMoney, thin } from '../../lib/chartScale';

const r1 = (n: number) => Math.round(n * 10) / 10;

export function bandGeometry(band: BandPoint[], w: number, h: number) {
  const first = band[0].jr_age;
  const lastAge = band[band.length - 1].jr_age;
  const peak = Math.max(1, ...band.map((p) => p.p90_cents));
  const step = niceStep(peak);
  const top = Math.ceil(peak / step) * step;
  const x = (age: number) => r1(((age - first) / Math.max(1, lastAge - first)) * w);
  const y = (c: number) => r1(h - (Math.max(0, c) / top) * h);
  const line = (k: 'p10_cents' | 'p50_cents' | 'p90_cents') => band.map((p) => `${x(p.jr_age)},${y(p[k])}`).join(' ');
  const area = [...band.map((p) => `${x(p.jr_age)},${y(p.p90_cents)}`), ...[...band].reverse().map((p) => `${x(p.jr_age)},${y(p.p10_cents)}`)].join(' ');
  const ticks: { y: number; label: string }[] = [];
  for (let v = 0; v <= top; v += step) ticks.push({ y: y(v), label: shortMoney(v) });
  const end = band[band.length - 1];
  return { x, y, area, mid: line('p50_cents'), low: line('p10_cents'), high: line('p90_cents'), ticks, firstAge: first, lastAge,
    ends: [y(end.p90_cents), y(end.p50_cents), y(end.p10_cents)] as [number, number, number] };
}

/** Top-to-bottom label positions, each at least `gap` below the one above. */
export function spreadLabels(ys: number[], gap: number): number[] {
  const out: number[] = [];
  for (const yv of ys) out.push(out.length && yv - out[out.length - 1] < gap ? out[out.length - 1] + gap : yv);
  return out;
}

export function bandWords(band: BandPoint[], bandAge: number, younger: string, jrName: string): string {
  const end = band[band.length - 1];
  const typical = `Retiring at ${bandAge}, in a typical market you'd have about ${millions(end.p50_cents)} left when ${younger} is 95.`;
  const empty = band.find((p) => p.jr_age >= bandAge && p.p10_cents <= 0);
  if (empty) return `${typical} In a rough market the money runs out when ${jrName} is about ${empty.jr_age}.`;
  if (end.p10_cents < end.p50_cents * 0.1) return `${typical} In a rough market it gets close to $0 but does not run out.`;
  return `${typical} In a rough market you'd have about ${millions(end.p10_cents)} left.`;
}
