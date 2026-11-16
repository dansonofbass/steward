import { useState } from 'react';
import type { FlowMonth } from '../../api/types';
import { Link } from '../../book/links';
import { STRIP_LABEL } from '../../lib/copy';
import { canHover } from '../../lib/useWide';
import { STRIP_H, STRIP_W, monthLong, monthReadout, monthTitle, stripBars } from '../cashflow/months';
import './strip.css';

/** The 12-month strip (JR, Oct 30: it stays, smaller, under the vital signs): income minus spending for each month,
 *  Spending's own figures (GET /api/home's flow.months), with the hover readout. The whole strip opens Spending on
 *  this month. Its own chunk, loaded once Home is ready. */
export default function MonthStrip({ months, asOf }: { months: FlowMonth[]; asOf: string }) {
  const [hover, setHover] = useState<number | null>(null);
  if (months.length === 0) return null;
  const now = months[months.length - 1];
  const { axis, bars } = stripBars(months, asOf);
  const slot = STRIP_W / months.length;
  const more = months.filter((m) => m.net_cents > 0).length;
  return (
    <Link className="mstrip" to={`/spending?month=${now.month}`} data-testid="flow-strip">
      <svg className="strip chart" viewBox={`0 0 ${STRIP_W} ${STRIP_H}`} preserveAspectRatio="none" role="img"
        aria-label={STRIP_LABEL.replace('{m}', String(months.length)).replace('{n}', String(more))}
        onMouseLeave={() => { setHover(null); }}>
        <line className="grid" x1="0" x2={STRIP_W} y1={axis} y2={axis} />
        {bars.map((b, i) => <rect key={months[i].month} className={b.cls} x={b.x} y={b.y} width={b.w} height={b.h} rx="2" />)}
        {/* A transparent full-height hit area per month, so a thin bar is easy to hover. Mouse only; touch is unchanged. */}
        {months.map((m, i) => (
          <rect key={`hit-${m.month}`} className="strip__hit" data-testid="strip-hit" x={i * slot} y={0} width={slot} height={STRIP_H}
            onMouseEnter={() => { if (canHover()) setHover(i); }} />
        ))}
      </svg>
      <span className="mstrip__foot">
        {hover !== null && months[hover]
          ? <span className="mstrip__readout" data-testid="flow-readout">{monthReadout(months[hover], asOf)}</span>
          : <><span>{monthLong(months[0].month)}</span><span>{monthTitle(now.month, asOf)}</span></>}
      </span>
    </Link>
  );
}
