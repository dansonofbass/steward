import { useRef } from 'react';
import { soundOn } from '../../lib/celebrations';
import { Acorn } from '../../ui/Acorn';
import { useAcornMotion } from '../../ui/useMoment';
import type { ToastCheer } from './toastText';

/** Phase 17 spec 3.7: the toast's cheer, with the acorn: a win face that hops, or the golden one that hops and sparkles
 *  (with the chime when Sound is on; a plain cheer adds no sound to the sort's own ding). */
export function SortCheer({ cheer }: { cheer: ToastCheer }) {
  const svg = useRef<SVGSVGElement>(null);
  useAcornMotion(svg, cheer.golden ? 'golden' : 'hop', cheer.golden && soundOn());
  return <><Acorn ref={svg} face={cheer.golden ? 'golden' : 'win'} size={18} />{cheer.line}</>;
}
