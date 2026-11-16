/** Review focus, After a sort and Gestures: how a focus card leaves. Transform and opacity only, through the Web Animations
 *  API, as celebrate.ts does. */
export type Leave = 'right' | 'left' | 'drop';

/** celebrate.ts's STAMP_LANDS_MS (280 + round(0.55 × 450)), copied so the Focus chunk never imports the celebrate chunk;
 *  motion.test.ts checks they agree. The slide waits for the stamp to land (P8). */
export const STAMP_LANDS_MS = 528;
export const LEAVE_MS = 220;
export const SPRING_MS = 260;

/** A sort leaves right, Snooze left, Ignore drops 12 px and fades. */
export function leaveFrames(how: Leave): Keyframe[] {
  if (how === 'drop') return [{ transform: 'none', opacity: 1 }, { transform: 'translateY(12px)', opacity: 0 }];
  const s = how === 'right' ? 1 : -1;
  return [{ transform: 'none', opacity: 1 }, { transform: `translateX(${s * 120}%) rotate(${s * 12}deg)`, opacity: 0 }];
}

export function play(el: Element, frames: Keyframe[], opts: KeyframeAnimationOptions): Animation | null {
  return typeof (el as HTMLElement).animate === 'function' ? (el as HTMLElement).animate(frames, opts) : null;
}
