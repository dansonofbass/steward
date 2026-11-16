import { reducedMotion } from './celebrations';

export const COLLAPSE_MS = 200;

/** A row leaving a list folds away over 200 ms, then `done` runs; at once under reduced motion (spec, Nothing unseen). */
export function collapse(el: HTMLElement | null, done: () => void): void {
  if (!el || reducedMotion() || typeof el.animate !== 'function') { done(); return; }
  const h = el.getBoundingClientRect().height;
  el.style.overflow = 'hidden';
  const a = el.animate([{ height: `${h}px`, opacity: 1 }, { height: '0px', opacity: 0 }], { duration: COLLAPSE_MS, easing: 'ease-in' });
  a.finished.then(done, done);
}
