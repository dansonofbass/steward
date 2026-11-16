import type { Drawer, Particle } from './engine';
import type { Look } from './season';

// Sorting redesign, Moments and order, counted from the burst (a sort's burst starts as its stamp settles, BURST_MS in
// celebrate.ts): streamers at 80 ms for about 900 ms; a spark per matching row from 300 ms, one every 100 ms, at most
// 12; the sunrise for 1.6 s. Each effect ends within 1.6 s of its own start.
export const STREAMER_DELAY = 0.08;
export const STREAMER_LIFE = 0.9;
export const SPARK_DELAY = 0.3;
export const SPARK_EVERY = 0.1;
export const SPARK_LIFE = 0.45;
export const SPARKS_MAX = 12;
export const SUNRISE_LIFE = 1.6;

const between = (a: number, b: number, r: () => number) => a + (b - a) * r();

/** Streamers burst from the card's left and right edges: up and out, then falling back. */
export function streamers(box: DOMRect, look: Look, n: number, r: () => number = Math.random): Particle[] {
  return Array.from({ length: n }, (_, i) => {
    const left = i % 2 === 0;
    return {
      x: left ? box.left : box.right, y: box.top + between(0.2, 0.8, r) * box.height,
      vx: (left ? -1 : 1) * between(120, 340, r), vy: -between(260, 520, r), g: 900, drag: 0.35,
      rot: between(0, Math.PI, r), vr: between(-12, 12, r), size: between(5, 8, r),
      color: look.colors[i % look.colors.length], shape: look.shape, age: -STREAMER_DELAY, life: STREAMER_LIFE,
    };
  });
}

/** A spark per matching row flies off the card's right edge. */
export function sparks(box: DOMRect, applied: number, color: string, r: () => number = Math.random): Particle[] {
  return Array.from({ length: Math.min(Math.max(0, applied), SPARKS_MAX) }, (_, i) => ({
    x: box.right - 8, y: box.top + box.height / 2 + between(-12, 12, r), vx: between(380, 520, r), vy: between(-140, 60, r),
    g: 120, drag: 0.6, rot: 0, vr: 0, size: 5, color, shape: 'spark' as const,
    age: -(SPARK_DELAY + i * SPARK_EVERY), life: SPARK_LIFE,
  }));
}

/** A colour's own hue at no opacity, so a gradient that fades to it never passes through grey (phase 17, spec 2.5). */
export function clear(hex: string): string {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex.trim());
  if (!m) return 'rgba(0, 0, 0, 0)';
  return `rgba(${parseInt(m[1], 16)}, ${parseInt(m[2], 16)}, ${parseInt(m[3], 16)}, 0)`;
}

/** The sunrise over "All caught up!": a warm glow rising from under the line, then fading. */
export function sunrise(box: DOMRect, colors: readonly [string, string]): Drawer {
  const cx = box.left + box.width / 2;
  const radius = Math.min(160, Math.max(60, box.width / 2));
  return {
    age: 0, life: SUNRISE_LIFE,
    draw: (ctx, t) => {
      const rise = Math.min(1, t / 0.6);
      const fade = t < 0.7 ? 1 : 1 - (t - 0.7) / 0.3;
      const cy = box.bottom + radius * 0.5 * (1 - rise);
      const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius);
      g.addColorStop(0, colors[0]);
      g.addColorStop(0.55, colors[1]);
      g.addColorStop(1, clear(colors[1]));
      ctx.globalAlpha = 0.55 * fade;
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(cx, cy, radius, Math.PI, 0);
      ctx.fill();
      ctx.globalAlpha = 1;
    },
  };
}
