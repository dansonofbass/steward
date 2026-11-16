import { useRef, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent, type RefObject } from 'react';
import { LEAVE_MS, play, SPRING_MS } from './motion';
import { type Box, commits, crossed, type Dir, labelStyle, type Lock, lockOf, progress, rotation, type Sample, UP_DAMP } from './swipe';

type Gesture = { id: number; x0: number; y0: number; box: Box; lock: Lock; samples: Sample[]; dx: number; dy: number; inZone: boolean; ticked: boolean; frame: number };
export type SwipeOpts = {
  enabled: boolean;
  reduced: boolean;
  /** Past the threshold: the card does the button's thing and says whether it flies out (a request went out) or
   *  springs back (the menu opened, a payer to choose, nothing to do). */
  onCommit: (dir: Dir, ticked: boolean) => 'fly' | 'back';
};
const DIRS: Dir[] = ['right', 'left', 'up'];

/** Review focus, Gestures: touch and pen only (P11), from anywhere on the card after 8 px (P12). The size is read once
 *  at pointerdown; moves are coalesced into one requestAnimationFrame write of transform and the labels' opacity and
 *  transform; settling uses the Web Animations API. No scroll or resize listeners, no layout reads while dragging. With
 *  swipes off it attaches nothing. */
export function useSwipe(card: RefObject<HTMLElement | null>, edge: RefObject<Record<Dir, HTMLElement | null>>, opts: SwipeOpts) {
  const g = useRef<Gesture | null>(null);
  const swallow = useRef(false);
  const anim = useRef<Animation | null>(null);
  const o = useRef(opts);
  o.current = opts;

  const labels = (dir: Dir | null, p: number) => {
    for (const d of DIRS) {
      const el = edge.current?.[d];
      if (!el) continue;
      const s = d === dir ? labelStyle(p) : { opacity: 0, scale: 0.8 };
      el.style.opacity = String(s.opacity);
      el.style.transform = o.current.reduced ? '' : `scale(${s.scale})`;
    }
  };
  const paint = () => {
    const s = g.current;
    const el = card.current;
    if (!s || !el) return;
    s.frame = 0;
    const { dir, p } = progress(s.lock, s.dx, s.dy, s.box);
    const x = s.lock === 'x' ? s.dx : 0;
    const y = s.lock === 'y' ? Math.min(0, s.dy) * UP_DAMP : 0;
    el.style.transform = `translate3d(${x}px, ${y}px, 0) rotate(${rotation(x, s.box.width, o.current.reduced)}deg)`;
    if (dir && p >= 1) el.dataset.armed = dir; else delete el.dataset.armed;
    labels(dir, p);
  };
  /** Back to rest: from `from` with a small overshoot in 260 ms, or at once under reduced motion. */
  const settle = (from: string) => {
    const el = card.current;
    if (!el) return;
    anim.current?.cancel();
    el.style.transform = '';
    el.style.willChange = '';
    delete el.dataset.armed;
    labels(null, 0);
    if (!o.current.reduced && from && from !== 'none') {
      anim.current = play(el, [{ transform: from }, { transform: 'none' }], { duration: SPRING_MS, easing: 'cubic-bezier(.3, 1.4, .5, 1)' });
    }
  };
  /** Out to ±120% and ±12° in 220 ms; it waits there until the reply lands (P8). Reduced motion: it stays and swaps. */
  const flyOut = (dir: 'left' | 'right') => {
    const el = card.current;
    if (!el) return;
    const from = el.style.transform || 'none';
    settle('');
    if (o.current.reduced) return;
    const s = dir === 'right' ? 1 : -1;
    const to = `translate3d(${s * 120}%, 0, 0) rotate(${s * 12}deg)`;
    anim.current = play(el, [{ transform: from }, { transform: to }], { duration: LEAVE_MS, easing: 'ease-in', fill: 'forwards' });
    el.dataset.flown = to;
  };
  const end = (commit: boolean) => {
    const s = g.current;
    g.current = null;
    if (!s) return;
    if (s.frame) cancelAnimationFrame(s.frame);
    swallow.current = s.lock !== null;           // a drag past slop swallows the click that follows (P12)
    const from = card.current?.style.transform || 'none';
    const dir = commit ? commits(s.lock, s.dx, s.dy, s.box, s.samples) : null;
    const how = dir ? o.current.onCommit(dir, s.ticked) : 'back';
    if (dir && dir !== 'up' && how === 'fly') flyOut(dir); else settle(from);
  };

  const handlers = {
    onPointerDown: (e: ReactPointerEvent<HTMLElement>) => {
      swallow.current = false;
      if (g.current || !e.isPrimary || (e.pointerType !== 'touch' && e.pointerType !== 'pen')) return;
      const r = e.currentTarget.getBoundingClientRect();
      g.current = { id: e.pointerId, x0: e.clientX, y0: e.clientY, box: { width: r.width, height: r.height }, lock: null,
        samples: [{ x: e.clientX, y: e.clientY, t: e.timeStamp }], dx: 0, dy: 0, inZone: false, ticked: false, frame: 0 };
      try { e.currentTarget.setPointerCapture?.(e.pointerId); } catch { /* the pointer is already gone */ }
    },
    onPointerMove: (e: ReactPointerEvent<HTMLElement>) => {
      const s = g.current;
      if (!s || e.pointerId !== s.id) return;
      s.dx = e.clientX - s.x0;
      s.dy = e.clientY - s.y0;
      s.samples.push({ x: e.clientX, y: e.clientY, t: e.timeStamp });
      if (s.samples.length > 12) s.samples.shift();
      if (!s.lock) {
        s.lock = lockOf(s.dx, s.dy);
        if (!s.lock) return;
        if (card.current) card.current.style.willChange = 'transform';
      }
      if (s.lock === 'down') return;
      const c = crossed(s.inZone, progress(s.lock, s.dx, s.dy, s.box).p);
      s.inZone = c.inZone;
      if (c.tick) { navigator.vibrate?.(10); s.ticked = true; }
      if (!s.frame) s.frame = requestAnimationFrame(paint);
    },
    onPointerUp: (e: ReactPointerEvent<HTMLElement>) => { if (g.current && e.pointerId === g.current.id) end(true); },
    onPointerCancel: (e: ReactPointerEvent<HTMLElement>) => { if (g.current && e.pointerId === g.current.id) end(false); },
    onClickCapture: (e: ReactMouseEvent<HTMLElement>) => {
      if (!swallow.current) return;
      swallow.current = false;
      e.preventDefault();
      e.stopPropagation();
    },
  };

  return {
    handlers: opts.enabled ? handlers : {},
    /** The reply failed: a card that flew out slides back in (the Failed state). */
    back: () => {
      const el = card.current;
      const to = el?.dataset.flown;
      if (!el || !to) return;
      delete el.dataset.flown;
      settle(to);
    },
  };
}
