import { useHistory } from '../../api/hooks';
import { millions, niceStep, shortMoney, thin } from '../../lib/chartScale';
import { LAST_90, NET_WORTH_TITLE } from '../../lib/copy';
import { monthLabel } from '../../lib/format';
import { useWide } from '../../lib/useWide';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { Sparkline } from '../../ui/Sparkline';
import { NET_WORTH_CAPTION, NET_WORTH_LABEL, NET_WORTH_SHADED, NOT_ENOUGH_HISTORY } from './netWorthCopy';
import './networth.css';

type Point = { date: string; net_worth_cents: number; investable_cents?: number };

/** One drawing at one size. useWide picks a narrow one for a phone and a wide one from 900 px (as the Plan's band chart
 *  does), so the labels come out about the same size on both instead of scaling up with the column. */
function Drawing({ pts, label, w: W, h: H, className }: { pts: Point[]; label: string; w: number; h: number; className: string }) {
  const vals = pts.map((p) => p.net_worth_cents);
  const all = [...vals, ...pts.map((p) => p.investable_cents ?? p.net_worth_cents)];
  const step = niceStep(Math.max(...all) - Math.min(...all) || Math.max(...all) || 1, 2);
  const lo = Math.floor(Math.min(...all) / step) * step;
  const hi = Math.max(lo + step, Math.ceil(Math.max(...all) / step) * step);
  const x = (i: number) => (i / (pts.length - 1)) * W;
  const y = (v: number) => H - ((v - lo) / (hi - lo)) * H;
  const ticks = [lo, (lo + hi) / 2, hi];
  const first = pts[0];
  const last = pts[pts.length - 1];
  return (
    <svg className={`nw-chart ${className}`} viewBox={`-44 -10 ${W + 44} ${H + 40}`} role="img" aria-label={label}>
      {ticks.map((t) => <g key={t}><line className="nw-grid" x1="0" x2={W} y1={y(t)} y2={y(t)} /><text x="-8" y={y(t) + 4} textAnchor="end">{shortMoney(t)}</text></g>)}
      {pts.every((p) => p.investable_cents !== undefined) && (
        <polygon className="nw-band" points={`0,${H} ${pts.map((p, i) => `${x(i).toFixed(1)},${y(Math.min(hi, Math.max(lo, p.investable_cents!))).toFixed(1)}`).join(' ')} ${W},${H}`} />
      )}
      <polyline className="nw-line" points={vals.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')} />
      <text x="0" y={H + 22}>{monthLabel(first.date)}</text>
      <text x={W} y={H + 22} textAnchor="end">{monthLabel(last.date)}</text>
    </svg>
  );
}

/** Net worth over time (plan subpages decision 6: moved from the Plan as it was), in its own chunk on Accounts. */
export default function NetWorthChart() {
  const wide = useWide();
  const q = useHistory(3650);
  // History is zero-filled before the first balance; the line starts at the first real point.
  const raw = q.data?.points ?? [];
  const start = raw.findIndex((p) => p.net_worth_cents !== 0);
  const real = start < 0 ? [] : raw.slice(start);
  const pts = thin(real, 120);
  // JR, Oct 30: Home's 90-day sparkline moved here. Drawn from the daily history this chart already loads, from the
  // first real balance, only when there are 90 days of it.
  const DAYS_90 = 90;
  const recent = real.length >= DAYS_90 ? real.slice(-DAYS_90).map((p) => p.net_worth_cents) : [];
  let body;
  if (q.isError) body = <Notice tone="error">{q.error.message}</Notice>;
  else if (!q.data) body = <Skeleton lines={3} />;
  else if (pts.length < 2) body = <p className="muted">{NOT_ENOUGH_HISTORY}</p>;
  else {
    const first = pts[0];
    const last = pts[pts.length - 1];
    const label = NET_WORTH_LABEL.replace('{from}', millions(first.net_worth_cents)).replace('{fromMonth}', monthLabel(first.date)).replace('{to}', millions(last.net_worth_cents)).replace('{toMonth}', monthLabel(last.date));
    body = (
      <>
        <Drawing pts={pts} label={label} w={wide ? 420 : 360} h={wide ? 150 : 120} className={wide ? 'nw-wide' : ''} />
      </>
    );
  }
  return (
    <section className="acct-sec" aria-labelledby="nw-h">
      <h2 id="nw-h">{NET_WORTH_TITLE}</h2>
      {body}
      {recent.length >= 2 && (
        <div className="nw-recent" data-testid="nw-recent">
          <Sparkline points={recent} />
          <p className="small muted">{LAST_90}</p>
        </div>
      )}
      <p className="small muted">{NET_WORTH_CAPTION}</p>
      {pts.length >= 2 && pts.every((p) => p.investable_cents !== undefined) && (
        <p className="small muted"><span className="nw-key" aria-hidden="true" /> {NET_WORTH_SHADED}</p>
      )}
    </section>
  );
}
