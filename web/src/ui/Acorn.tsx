import type { Ref } from 'react';
import { season } from '../lib/season';
import { MARK, type Paint } from './markArt';
import './Acorn.css';

export type Face = 'win' | 'golden' | 'resting' | 'oops';
export type AcornSeason = 'fall' | 'snow' | null;

// The faces from the Nov 2 design round (acorn-states, acorn-golden-v2 option A, acorn-oops-v3), on the mark's 32 grid.
// Win: two dot eyes (below) and a small smile. Golden: arched ^ ^ eyes and the same smile. Resting: closed eyes, no
// mouth. Oops: > < eyes and a small wavy mouth, plus a sweat drop.
export const FACE_LINES: Record<Face, string> = {
  win: 'M13 26.2q1.5 1 3 0',
  golden: 'M10.8 23.6q1.2-1.6 2.4 0M15.8 23.6q1.2-1.6 2.4 0M12.8 26q1.7 1.3 3.4 0',
  resting: 'M10.8 23q1.2.9 2.4 0M15.8 23q1.2.9 2.4 0',
  oops: 'M10.6 21.8l2.2 1.3-2.2 1.3M18.4 21.8l-2.2 1.3 2.2 1.3M13.2 26.6q1.3-.8 2.6 0',
};
const SWEAT = 'M22.6 19.4c.8 1.1 1.2 1.8 1.2 2.4a1.2 1.2 0 0 1-2.4 0c0-.6.4-1.3 1.2-2.4z';
const SNOW = 'M4.2 13.5C5 10 9 8.6 14.5 8.6S24 10 24.8 13.5c-1.2-.8-2-.2-3 .3-1-.9-2.2-.6-3 .2-1.2-1-2.6-.8-3.6.1-1-.9-2.5-.9-3.5 0-1-.8-2.4-.9-3.4 0-1-.6-2.4-.6-3.6-.6z';
// The mark's paints, without its tile: the acorn is the nut, the soft tint the leaf, and the tile's line the vein.
const PAINT: Record<Paint, string> = { ink: 'acorn__nut', soft: 'acorn__leaf', tile: 'acorn__vein' };

/** Spec 3.1: the leaf turns orange from October 1 to November 30; a snow cap sits on the nut in December. */
export function acornSeason(now: Date): AcornSeason {
  const s = season(now);
  return s === 'leaves' ? 'fall' : s === 'snow' ? 'snow' : null;
}

type Props = { face: Face; size?: number; label?: string; className?: string; season?: AcornSeason; ref?: Ref<SVGSVGElement> };

/** The acorn companion (phase 17 spec 3.1, D2, D8-D10): the mark's acorn with a tiny face, no tile, in --acorn-*
 *  tokens so it reads in every sky phase. Still; motion is the celebrate chunk's (celebrate/acorn.ts), on the
 *  [data-move] group. Decorative unless `label` is given. `season` overrides today's (the design page shows both). */
export function Acorn({ face, size = 32, label, className, season: chosen, ref }: Props) {
  const s = chosen === undefined ? acornSeason(new Date()) : chosen;
  const cls = ['acorn', `acorn--${face}`, s ? `acorn--${s}` : '', className ?? ''].filter(Boolean).join(' ');
  return (
    <svg ref={ref} className={cls} data-face={face} data-season={s ?? undefined} width={size} height={size} viewBox="0 0 32 32"
      {...(label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true, focusable: false })}>
      <g className="acorn__all" data-move="">
        {MARK.medium.parts.map((p) => (p.fill
          ? <path key={p.d} className={PAINT[p.fill]} d={p.d} />
          : <path key={p.d} className={`${PAINT[p.stroke!]}-line`} d={p.d} fill="none" strokeWidth={p.width} strokeLinecap="round" />))}
        {s === 'snow' && <path className="acorn__snow" d={SNOW} />}
        {face === 'win' && <><circle className="acorn__eye" cx="12" cy="23" r="1.1" /><circle className="acorn__eye" cx="17" cy="23" r="1.1" /></>}
        <path className="acorn__face" d={FACE_LINES[face]} />
        {face === 'oops' && <path className="acorn__sweat" d={SWEAT} />}
      </g>
    </svg>
  );
}
