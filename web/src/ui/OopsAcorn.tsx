import { useRef } from 'react';
import { useIsHousehold } from '../book/BookContext';
import { momentAllowed } from '../lib/momentAllowed';
import { Acorn } from './Acorn';
import { useAcornMotion } from './useMoment';

/** Phase 17 spec 3.5 row 2: Steward's own hiccup (a file it couldn't read, a sync that failed, the gateway away), beside
 *  the screen's own plain message and next step. One wince, never a sound, never a joke; nothing in a parent book. */
export function OopsAcorn({ size = 20 }: { size?: number }) {
  const allowed = momentAllowed('oops', { parent: !useIsHousehold() });
  const svg = useRef<SVGSVGElement>(null);
  useAcornMotion(svg, allowed.motion ? 'wince' : null);
  return allowed.face ? <Acorn ref={svg} face="oops" size={size} className="oops-acorn" /> : null;
}
