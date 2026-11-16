import { millions, niceStep, shortMoney, thin } from '../../../lib/chartScale';
import { dateLabel, monthLabel } from '../../../lib/format';
import { useWide } from '../../../lib/useWide';
import type { SeriesPoint } from './api';
import { BALANCE_KEY, CHART_LABEL, NOT_ENOUGH_HISTORY, SINCE_WATCHING, YOU_PUT_IN } from './copy';

/** The balance against the running total put in, from the first balance (investment views spec). One SVG, drawn once at
 *  the size useWide picks, as the Plan's band chart is: 320 x 140 on a phone, 860 x 240 from 900 px, where the CSS stops it
 *  growing past its own width so the labels stay at text size (about 12 px) instead of scaling up with the column. */
export function GrowthChart({ points, since, today = new Date() }: { points: SeriesPoint[]; since: string | null; today?: Date }) {
  const wide = useWide();
  if (!since || points.length < 2) return <p className="muted small">{NOT_ENOUGH_HISTORY}</p>;
  const [W, H] = wide ? [860, 240] : [320, 140];
  const pts = thin(points, 120);
  const vals = pts.flatMap((p) => [p.balance_cents, p.put_in_cents]);
  const min = Math.min(0, ...vals);
  const max = Math.max(...vals);
  const step = niceStep(max - min || 1, 2);
  const lo = Math.floor(min / step) * step;
  const hi = Math.max(lo + step, Math.ceil(max / step) * step);
  const x = (i: number) => (i / (pts.length - 1)) * W;
  const y = (v: number) => H - ((v - lo) / (hi - lo)) * H;
  const line = (key: 'balance_cents' | 'put_in_cents') => pts.map((p, i) => `${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`).join(' ');
  const first = pts[0];
  const last = pts[pts.length - 1];
  const label = CHART_LABEL.replace('{from}', millions(first.balance_cents)).replace('{since}', monthLabel(first.date))
    .replace('{to}', millions(last.balance_cents)).replace('{in}', millions(last.put_in_cents));
  return (
    <figure className="inv-chart">
      <svg viewBox={`-48 -10 ${W + 52} ${H + 34}`} role="img" aria-label={label} className={wide ? 'is-wide' : undefined}>
        {[lo, (lo + hi) / 2, hi].map((t) => (
          <g key={t}><line className="grid" x1="0" x2={W} y1={y(t)} y2={y(t)} /><text x="-8" y={y(t) + 4} textAnchor="end">{shortMoney(t)}</text></g>
        ))}
        <polyline className="put" points={line('put_in_cents')} />
        <polyline className="bal" points={line('balance_cents')} />
        <text x="0" y={H + 22}>{monthLabel(first.date)}</text>
        <text x={W} y={H + 22} textAnchor="end">{monthLabel(last.date)}</text>
      </svg>
      <figcaption>
        <span className="inv-legend">
          <span className="inv-key is-bal" aria-hidden="true" />{BALANCE_KEY}
          <span className="inv-key is-put" aria-hidden="true" />{YOU_PUT_IN}
        </span>
        <span className="small muted">{SINCE_WATCHING.replace('{date}', dateLabel(since, today))}</span>
      </figcaption>
    </figure>
  );
}
