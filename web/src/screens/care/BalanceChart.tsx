import { dollars } from '../../lib/format';
import type { CareYear } from './api';
import * as C from './copy';

const W = 300;
const H = 96;
const PAD = 6;

/** Savings each year as one line from zero up; a dashed mark in the year the money runs out; a ring where the Medi-Cal
 *  limit is first met. The legend says each in words (no colour-only meaning). */
export function BalanceChart({ years, runsOut, mediCal }: { years: CareYear[]; runsOut: number | null; mediCal: number | null }) {
  if (years.length === 0) return null;
  const max = Math.max(...years.map((y) => y.balance_cents), 1);
  const x = (i: number) => (years.length === 1 ? W / 2 : (i / (years.length - 1)) * W);
  const y = (v: number) => H - PAD - (Math.max(v, 0) / max) * (H - PAD * 2);
  const d = years.map((r, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(r.balance_cents).toFixed(1)}`).join(' ');
  const at = (year: number | null) => (year === null ? -1 : years.findIndex((r) => r.year === year));
  const out = at(runsOut);
  const mc = at(mediCal);
  const first = years[0];
  const last = years[years.length - 1];
  const label = C.fill(C.CHART_LABEL, { from: dollars(first.balance_cents), start: String(first.year), to: dollars(last.balance_cents), end: String(last.year) })
    + (out >= 0 ? C.fill(C.CHART_OUT, { year: String(runsOut) }) : '');
  return (
    <figure className="care-chart">
      <svg role="img" aria-label={label} viewBox={`0 0 ${W} ${H}`}>
        <line className="care-chart__base" x1="0" x2={W} y1={y(0)} y2={y(0)} />
        <path className="care-chart__line" d={d} />
        {out >= 0 && <line className="care-chart__out" x1={x(out)} x2={x(out)} y1={PAD / 2} y2={H - PAD / 2} />}
        {mc >= 0 && <circle className="care-chart__mc" cx={x(mc)} cy={y(years[mc].balance_cents)} r="5" />}
      </svg>
      <figcaption className="care-legend small muted">
        <span><svg width="20" height="20" aria-hidden="true"><line className="care-chart__line" x1="2" x2="18" y1="10" y2="10" /></svg>{C.LEGEND_SAVINGS}</span>
        {out >= 0 && <span><svg width="20" height="20" aria-hidden="true"><line className="care-chart__out" x1="10" x2="10" y1="2" y2="18" /></svg>{C.fill(C.LEGEND_OUT, { year: String(runsOut) })}</span>}
        {mc >= 0 && <span><svg width="20" height="20" aria-hidden="true"><circle className="care-chart__mc" cx="10" cy="10" r="5" /></svg>{C.fill(C.LEGEND_MC, { year: String(mediCal) })}</span>}
      </figcaption>
    </figure>
  );
}
