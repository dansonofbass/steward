/** Review focus, Gestures (P9): pure functions of the pointer samples, so they test without a DOM. */
export const SLOP = 8;
export const SIDE_FRAC = 0.3;
export const UP_FRAC = 0.25;
export const MAX_PX = 120;
export const FLICK_V = 0.6;           // px per ms
export const FLICK_MIN = 48;
export const FLICK_WINDOW_MS = 80;
export const ROT_MAX = 8;             // degrees
export const UP_DAMP = 0.6;           // up follows the finger at 0.6×, so it feels heavier

export type Dir = 'right' | 'left' | 'up';
export type Lock = 'x' | 'y' | 'down' | null;
export type Sample = { x: number; y: number; t: number };
export type Box = { width: number; height: number };

/** Nothing until 8 px of travel; then horizontal when |dx| ≥ |dy|, else up, or down (which does nothing). */
export function lockOf(dx: number, dy: number): Lock {
  if (Math.max(Math.abs(dx), Math.abs(dy)) < SLOP) return null;
  if (Math.abs(dx) >= Math.abs(dy)) return 'x';
  return dy < 0 ? 'y' : 'down';
}

export const sideAt = (box: Box): number => Math.min(box.width * SIDE_FRAC, MAX_PX);
export const upAt = (box: Box): number => Math.min(box.height * UP_FRAC, MAX_PX);

/** Which way, and how far towards the threshold (1 at the threshold). */
export function progress(lock: Lock, dx: number, dy: number, box: Box): { dir: Dir | null; p: number } {
  if (lock === 'x') {
    const at = sideAt(box);
    return { dir: dx >= 0 ? 'right' : 'left', p: at > 0 ? Math.abs(dx) / at : 0 };
  }
  if (lock === 'y') {
    const at = upAt(box);
    return { dir: 'up', p: at > 0 ? Math.max(0, -dy) / at : 0 };
  }
  return { dir: null, p: 0 };
}

/** The speed over the last 80 ms of samples. */
export function velocity(samples: readonly Sample[]): { vx: number; vy: number } {
  const last = samples[samples.length - 1];
  if (!last) return { vx: 0, vy: 0 };
  const first = samples.find((s) => last.t - s.t <= FLICK_WINDOW_MS) ?? last;
  const dt = last.t - first.t;
  return dt > 0 ? { vx: (last.x - first.x) / dt, vy: (last.y - first.y) / dt } : { vx: 0, vy: 0 };
}

/** Past the threshold, or a flick the same way with at least 48 px of travel. */
export function commits(lock: Lock, dx: number, dy: number, box: Box, samples: readonly Sample[]): Dir | null {
  const { dir, p } = progress(lock, dx, dy, box);
  if (!dir) return null;
  if (p >= 1) return dir;
  const { vx, vy } = velocity(samples);
  if (dir === 'up') return vy <= -FLICK_V && -dy >= FLICK_MIN ? 'up' : null;
  return Math.abs(vx) >= FLICK_V && Math.abs(dx) >= FLICK_MIN && Math.sign(vx) === Math.sign(dx) ? dir : null;
}

/** The edge label: opacity follows progress; it grows from 0.8 to 1.15 at the threshold, then holds. */
export function labelStyle(p: number): { opacity: number; scale: number } {
  const q = Math.min(1, Math.max(0, p));
  return { opacity: q, scale: q >= 1 ? 1.15 : Math.round((0.8 + 0.35 * q) * 1000) / 1000 };
}

/** dx / width × 8°, capped at ±8°; none under reduced motion (P10). */
export function rotation(dx: number, width: number, reduced: boolean): number {
  if (reduced || width <= 0) return 0;
  return Math.max(-ROT_MAX, Math.min(ROT_MAX, (dx / width) * ROT_MAX));
}

/** A haptic tick each time progress crosses into the commit zone (P33). */
export function crossed(wasIn: boolean, p: number): { inZone: boolean; tick: boolean } {
  const inZone = p >= 1;
  return { inZone, tick: inZone && !wasIn };
}
