import { LAST_90 } from '../lib/copy';
import { money } from '../lib/format';
import './Sparkline.css';

const W = 300;
const H = 60;
const PAD = 4;

/** Inline SVG trend line: no axes, a faint baseline at the first value. `points` are cents. */
export function Sparkline({ points, stroke = 'var(--accent-text)' }: { points: number[]; stroke?: string }) {
  if (points.length === 0) return null;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const x = (i: number) => (points.length === 1 ? W / 2 : (i / (points.length - 1)) * W);
  const y = (v: number) => H - PAD - ((v - min) / span) * (H - PAD * 2);
  const d = points.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ');
  const label = `${LAST_90}: from ${money(points[0])} to ${money(points[points.length - 1])}`;
  return (
    <svg className="sparkline" role="img" aria-label={label} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" width="100%" height={H}>
      <title>{label}</title>
      <line x1="0" x2={W} y1={y(points[0])} y2={y(points[0])} stroke="var(--line)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      <path d={d} fill="none" stroke={stroke} strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
