import { useEffect, type RefObject } from 'react';
import type { AcornMotion } from '../celebrate/acorn';
import { withCelebrate } from '../lib/celebrations';

/** Phase 17: plays `motion` on the acorn (or tree) `ref` points at, through the celebrate chunk, once per mount; null
 *  plays nothing. While celebrations are off or motion is reduced the chunk is never asked for and the drawing stays
 *  still. The motion stops when the drawing goes (the doze loops until then). */
export function useAcornMotion(ref: RefObject<SVGSVGElement | null>, motion: AcornMotion | null, sound = false): void {
  useEffect(() => {
    const svg = ref.current;
    if (!svg || !motion) return;
    let gone = false;
    let stop: (() => void) | undefined;
    void withCelebrate((c) => { if (!gone) stop = c.acorn({ svg, motion, sound }); });
    return () => { gone = true; stop?.(); };
  }, [ref, motion, sound]);
}

/** A win's coins or sprout over `ref`'s element, once per mount, the same way. */
export function useWinMoment(ref: RefObject<HTMLElement | null>, name: 'coins' | 'sprout' | null, sound = false): void {
  useEffect(() => {
    const host = ref.current;
    if (!host || !name) return;
    let gone = false;
    let off: (() => void) | undefined;
    void withCelebrate((c) => { if (!gone) off = c.winMoment({ host, name, sound }); });
    return () => { gone = true; off?.(); };
  }, [ref, name, sound]);
}
