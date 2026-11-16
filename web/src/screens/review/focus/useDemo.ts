import { useEffect, useState, type RefObject } from 'react';
import { type DemoState, setDemo } from '../../../lib/reviewPrefs';
import type { Dir } from './swipe';

export const DEMO_DELAY_MS = 500;
export const DEMO_MS = 1400;

/** P13: only on a touch screen, with swipes on, motion allowed, and the demo not seen on this device. */
export const shouldNudge = (o: { coarse: boolean; swipe: boolean; reduced: boolean; state: DemoState }): boolean =>
  o.coarse && o.swipe && !o.reduced && o.state === null;

// About 1.4 s: 28 px right with the right label at 60%, back; a 150 ms pause; the same to the left. Transform and opacity.
const CARD: Keyframe[] = [
  { transform: 'none', offset: 0 }, { transform: 'translateX(28px)', offset: 0.22 }, { transform: 'none', offset: 0.45 },
  { transform: 'none', offset: 0.55 }, { transform: 'translateX(-28px)', offset: 0.78 }, { transform: 'none', offset: 1 },
];
const RIGHT: Keyframe[] = [{ opacity: 0, offset: 0 }, { opacity: 0.6, offset: 0.22 }, { opacity: 0, offset: 0.45 }, { opacity: 0, offset: 1 }];
const LEFT: Keyframe[] = [{ opacity: 0, offset: 0 }, { opacity: 0, offset: 0.55 }, { opacity: 0.6, offset: 0.78 }, { opacity: 0, offset: 1 }];

/** The one-time nudge on the first focus card, 500 ms after it shows. Any pointerdown or keydown cancels it. It marks
 *  the device `nudged` when it starts; reviewPrefs keeps a page-load flag when storage throws. */
export function useDemo(on: boolean, card: RefObject<HTMLElement | null>, edge: RefObject<Record<Dir, HTMLElement | null>>): boolean {
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    if (!on) return;
    const anims: Animation[] = [];
    let start = 0;
    let end = 0;
    const stop = () => {
      window.clearTimeout(start);
      window.clearTimeout(end);
      for (const a of anims) a.cancel();
      setPlaying(false);
      document.removeEventListener('pointerdown', stop, true);
      document.removeEventListener('keydown', stop, true);
    };
    start = window.setTimeout(() => {
      setPlaying(true);
      setDemo('nudged');
      const go = (el: HTMLElement | null | undefined, frames: Keyframe[]) => {
        if (el && typeof el.animate === 'function') anims.push(el.animate(frames, { duration: DEMO_MS, easing: 'ease-in-out' }));
      };
      go(card.current, CARD);
      go(edge.current?.right, RIGHT);
      go(edge.current?.left, LEFT);
      end = window.setTimeout(stop, DEMO_MS);
    }, DEMO_DELAY_MS);
    document.addEventListener('pointerdown', stop, true);
    document.addEventListener('keydown', stop, true);
    return stop;
  }, [on, card, edge]);
  return playing;
}
