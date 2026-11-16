import type { Ref } from 'react';
import { Acorn } from './Acorn';
import './OakTree.css';

// The growth path from the Nov 2 mockup (acorn-states, "Growing toward an oak"): sprout, sapling, young oak, oak, and
// the oak with its acorns. Stage 0 is the acorn itself, resting. Circles: [second shade, cx, cy, r].
type Circle = readonly [boolean, number, number, number];
type Art = { w: number; h: number; trunk: string; width: number; leaves?: string; circles: readonly Circle[]; acorns?: boolean };
const OAK: Circle[] = [[true, 11, 32, 11], [true, 41, 28, 12], [false, 26, 20, 17], [false, 16, 18, 9], [false, 37, 15, 9]];
const ART: Record<1 | 2 | 3 | 4 | 5, Art> = {
  1: { w: 32, h: 44, trunk: 'M16 44V30', width: 2, leaves: 'M16 30c-1-5-5-7-9-6 1 4 4 6 9 6zM16 30c1-6 5-8 10-7-1 5-5 7-10 7z', circles: [] },
  2: { w: 32, h: 52, trunk: 'M16 52V22M16 34l-6-5M16 30l6-6', width: 2.2, circles: [[false, 9, 27, 5], [false, 23, 22, 6], [true, 16, 16, 7]] },
  3: { w: 40, h: 62, trunk: 'M20 62V28M20 40l-9-6M20 36l9-8', width: 3, circles: [[true, 10, 28, 9], [true, 30, 24, 10], [false, 20, 16, 13]] },
  4: { w: 52, h: 72, trunk: 'M26 72V34M26 46l-12-8M26 42l12-10', width: 4.5, circles: OAK },
  5: { w: 52, h: 72, trunk: 'M26 72V34M26 46l-12-8M26 42l12-10', width: 4.5, circles: OAK, acorns: true },
};

/** Phase 17 spec 3.4: the book's tree at its stage, `size` tall. An image with its name; it moves only through the
 *  celebrate chunk, on its [data-move] group. */
export function OakTree({ stage, size = 56, label, ref }: { stage: number; size?: number; label: string; ref?: Ref<SVGSVGElement> }) {
  if (stage <= 0) return <Acorn ref={ref} face="resting" size={Math.round(size * 0.6)} label={label} />;
  const a = ART[Math.min(stage, 5) as 1 | 2 | 3 | 4 | 5];
  return (
    <svg ref={ref} className="oak" data-stage={stage} role="img" aria-label={label} viewBox={`0 0 ${a.w} ${a.h}`}
      height={size} width={Math.round((size * a.w) / a.h)}>
      <g data-move="">
        <path className="oak__trunk" d={a.trunk} strokeWidth={a.width} />
        {a.leaves && <path className="oak__crown" d={a.leaves} />}
        {a.circles.map(([second, cx, cy, r]) => <circle key={`${cx}-${cy}`} className={second ? 'oak__crown-2' : 'oak__crown'} cx={cx} cy={cy} r={r} />)}
        {a.acorns && <><circle className="oak__acorn" cx="20" cy="24" r="1.6" /><circle className="oak__acorn" cx="33" cy="22" r="1.6" /></>}
      </g>
    </svg>
  );
}
