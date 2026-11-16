import type { TrendRow } from '../../api/types';
import * as C from './copy';
import { fill, monthInitial, monthOnly } from './model';

const W = 300;
const H = 52;
const TOP = 6;
const BASE = 50;
const r1 = (n: number) => n.toFixed(1);

/** One category's months as small bars against its target (or a fixed cost's expected amount), drawn dashed.
 *  The month still in progress is faded and labelled "so far" (ruling 23); the page's count leaves it out.
 *  The bars stretch to the card; the month labels are HTML underneath so the text never distorts. The whole chart is
 *  hidden from screen readers: the card's link already says the category, the count and the target once. */
export function TrendBars({ row, months, current }: { row: TrendRow; months: string[]; current: string }) {
  const line = row.kind === 'everyday' ? row.target_cents : row.expected_cents;
  const spent = months.map((_, i) => Math.max(0, row.spent[i] ?? 0));
  const max = Math.max(line ?? 0, ...spent, 1) * 1.1;
  const y = (v: number) => BASE - (v / max) * (BASE - TOP);
  const slot = W / months.length;
  const bw = Math.min(18, slot * 0.6);
  return (
    <>
      <svg className="sp-chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
        {line !== null && <line className="sp-chart__target" x1="0" x2={W} y1={r1(y(line))} y2={r1(y(line))} />}
        {months.map((m, i) => {
          const v = spent[i];
          const over = row.kind === 'everyday' && line !== null && v > line;
          return <rect key={m} className={`sp-chart__bar${over ? ' is-over' : ''}${m === current ? ' so-far' : ''}`} x={r1(i * slot + (slot - bw) / 2)} y={r1(y(v))} width={r1(bw)} height={r1(BASE - y(v))} />;
        })}
      </svg>
      <div className="sp-chart__months" style={{ gridTemplateColumns: `repeat(${months.length}, 1fr)` }} aria-hidden="true">
        {months.map((m) => <span key={m} className="sp-chart__month" title={m === current ? fill(C.SO_FAR_BAR, { month: monthOnly(m) }) : undefined}>{m === current ? C.SO_FAR : monthInitial(m)}</span>)}
      </div>
    </>
  );
}
