import { useWide } from '../../lib/useWide';
import type { PlanResult } from './api';
import { BAND_CAPTION, BAND_END_SPOUSE, BAND_LABEL, BAND_START, BAND_TITLE, GOOD, NO_BAND, RETIRE_AT, ROUGH, ROUGH_TO_GOOD, TYPICAL, TYPICAL_MARKETS } from './copy';
import { bandGeometry, bandWords, spreadLabels } from './band';
import type { People } from './people';

function Drawing({ result, people, w, h, className }: { result: PlanResult; people: People; w: number; h: number; className: string }) {
  const g = bandGeometry(result.band, w, h);
  const age = result.band_age!;
  const [good, typical, rough] = spreadLabels(g.ends, 14);
  const endLabel = people.younger === people.names.spouse ? BAND_END_SPOUSE.replace('{age}', String(g.lastAge)).replace('{spouse}', people.names.spouse) : String(g.lastAge);
  return (
    <svg className={`chart ${className}`} viewBox={`-44 -16 ${w + 48} ${h + 40}`} role="img"
      aria-label={BAND_LABEL.replace('{name}', people.names.jr).replace('{first}', String(g.firstAge)).replace('{last}', String(g.lastAge))}>
      {g.ticks.map((t) => (
        <g key={t.label}><line className="grid" x1="0" x2={w} y1={t.y} y2={t.y} /><text x="-6" y={t.y + 4} textAnchor="end">{t.label}</text></g>
      ))}
      <polygon className="band-area" points={g.area} />
      <polyline className="band-edge" points={g.high} />
      <polyline className="band-edge" points={g.low} />
      <polyline className="band-mid" points={g.mid} />
      <line className="retire" x1={g.x(age)} x2={g.x(age)} y1="-6" y2={h} />
      <text x={g.x(age) - 6} y="0" textAnchor="end" className="t-strong">{RETIRE_AT.replace('{age}', String(age))}</text>
      <text x={w - 4} y={good} textAnchor="end" className="end-label">{GOOD}</text>
      <text x={w - 4} y={typical} textAnchor="end" className="end-label">{TYPICAL}</text>
      <text x={w - 4} y={rough - 4} textAnchor="end" className="end-label">{ROUGH}</text>
      <text x="0" y={h + 20}>{BAND_START.replace('{name}', people.names.jr).replace('{age}', String(g.firstAge))}</text>
      <text x={g.x(age)} y={h + 20} textAnchor="middle">{age}</text>
      <text x={w} y={h + 20} textAnchor="end">{endLabel}</text>
    </svg>
  );
}

/** Design decision 6: the band with Good, Typical and Rough at the line ends, and one plain sentence above it. */
export function BandChart({ result, people }: { result: PlanResult; people: People }) {
  const wide = useWide();
  const ok = result.band_age !== null && result.band.length >= 2;
  return (
    <section className="sec band" aria-labelledby="band-h" data-testid="band">
      <h2 id="band-h">{BAND_TITLE}</h2>
      {!ok ? <p className="band__words">{NO_BAND}</p> : (
        <>
          <p className="band__words">{bandWords(result.band, result.band_age!, people.younger, people.names.jr)}</p>
          <div className="legend">
            <span><i className="swatch swatch--line" />{TYPICAL_MARKETS}</span>
            <span><i className="swatch swatch--band" />{ROUGH_TO_GOOD}</span>
            <span><i className="swatch swatch--dash" />{RETIRE_AT.replace('{age}', String(result.band_age))}</span>
          </div>
          <div className="chart-wrap">
            {/* One drawing (plan subpages): its geometry follows the width, so the labels stay readable on both. */}
            <Drawing result={result} people={people} w={wide ? 860 : 300} h={wide ? 240 : 180} className={wide ? 'chart--wide' : ''} />
          </div>
          <p className="small muted">{BAND_CAPTION}</p>
        </>
      )}
    </section>
  );
}
