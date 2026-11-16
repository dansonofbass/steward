import { useEffect, type ComponentProps, type ComponentType } from 'react';
import { lazyScreen } from '../../../lib/lazyScreen';
import type FocusView from './Focus';

type Props = ComponentProps<typeof FocusView>;

/** The chunk couldn't be fetched (a deploy replaced it while the page was open): Review shows the list for this visit
 *  (engineering choice 15). */
function Missing({ onMissing }: Props) {
  useEffect(() => { onMissing(); }, [onMissing]);
  return null;
}

export const loadFocus = (load: () => Promise<{ default: ComponentType<Props> }> = () => import('./Focus')) =>
  load().catch(() => ({ default: Missing }));
/** Review's focus view (review focus P26): its own chunk, with the card, the gestures, the keys, the demo and the ⋯ menu. */
export const Focus = lazyScreen(() => loadFocus());

/** Loads the Focus chunk, and the Review page that shows it, ahead of the first visit. A failure isn't retried: the render uses the same load. */
export function preloadFocus(): void {
  void Focus.preload();
  void import('../../Review');          // the page that shows it is a chunk too, so the Review tab warms both
}

/** When the browser is idle, or soon after the first paint where requestIdleCallback is missing. Returns a cancel. */
export function preloadFocusWhenIdle(): () => void {
  const w = window as Window & { requestIdleCallback?: (cb: () => void) => number; cancelIdleCallback?: (id: number) => void };
  if (typeof w.requestIdleCallback === 'function') {
    const id = w.requestIdleCallback(preloadFocus);
    return () => { w.cancelIdleCallback?.(id); };
  }
  const id = window.setTimeout(preloadFocus, 1);
  return () => { window.clearTimeout(id); };
}
