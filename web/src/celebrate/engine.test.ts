import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  SPARK_DELAY, SPARK_EVERY, SPARK_LIFE, SPARKS_MAX, STREAMER_DELAY, STREAMER_LIFE, SUNRISE_LIFE, sparks, streamers,
} from './effects';
import { Engine, particleCap, step, type Particle } from './engine';
import { look, season } from './season';

let frames: FrameRequestCallback[] = [];
let clock = 0;
const pump = (ms: number) => {
  const end = clock + ms;
  while (frames.length && clock < end) { clock += 16; frames.shift()!(clock); }
};
const ctx = new Proxy({} as Record<string | symbol, unknown>, {
  get: (t, k) => (k in t ? t[k] : (t[k] = vi.fn(() => ({ addColorStop: vi.fn() })))),
  set: (t, k, v) => { t[k] = v; return true; },
});
const BOX = { left: 100, right: 400, top: 100, bottom: 200, width: 300, height: 100 } as DOMRect;
const SUMMER = look(new Date(2027, 6, 4), ['#123']);
const hidden = (on: boolean) => Object.defineProperty(document, 'hidden', { configurable: true, get: () => on });

beforeEach(() => {
  frames = [];
  clock = 0;
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { frames.push(cb); return frames.length; });
  vi.stubGlobal('cancelAnimationFrame', () => { frames = []; });
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation((() => ctx) as never);
  hidden(false);
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); hidden(false); document.body.innerHTML = ''; });

describe('the canvas engine (sorting redesign, Performance 2)', () => {
  it('makes one canvas at the first burst and removes it once idle', () => {
    const e = new Engine(() => 40);
    e.add(streamers(BOX, SUMMER, 28));
    e.add(sparks(BOX, 3, '#0a0'));
    expect(document.querySelectorAll('canvas.cel-canvas')).toHaveLength(1);
    pump(1700);
    expect(document.querySelector('canvas.cel-canvas')).toBeNull();
    expect(frames).toHaveLength(0);
  });

  it('caps the particles at 40, or 20 on a small device, dropping the oldest', () => {
    expect(particleCap({ cores: 8, coarse: false, narrow: false })).toBe(40);
    expect(particleCap({ coarse: false, narrow: false })).toBe(40);
    expect(particleCap({ cores: 4, coarse: false, narrow: false })).toBe(20);
    expect(particleCap({ cores: 8, coarse: true, narrow: false })).toBe(20);
    expect(particleCap({ cores: 8, coarse: false, narrow: true })).toBe(20);
    const e = new Engine(() => 20);
    e.add(streamers(BOX, SUMMER, 50));
    expect(e.particles).toHaveLength(20);
  });

  it('stops at once and removes the canvas when the tab is hidden, and starts nothing while hidden', () => {
    const e = new Engine(() => 40);
    e.add(streamers(BOX, SUMMER, 10));
    pump(100);
    hidden(true);
    pump(16);
    expect(document.querySelector('canvas.cel-canvas')).toBeNull();
    expect(e.particles).toHaveLength(0);
    e.add(streamers(BOX, SUMMER, 10));
    expect(document.querySelector('canvas.cel-canvas')).toBeNull();
  });

  it('moves a particle under gravity and ends it at the end of its life', () => {
    const p: Particle = { x: 0, y: 0, vx: 100, vy: 0, g: 100, drag: 1, rot: 0, vr: 0, size: 4, color: '#000', shape: 'spark', age: 0, life: 0.5 };
    expect(step(p, 0.1)).toBe(true);
    expect([p.x, p.vy]).toEqual([10, 10]);
    expect(step(p, 0.5)).toBe(false);
  });

  it('ends every effect within 1.6 s of its own start, with a spark per matching row up to 12', () => {
    expect(STREAMER_DELAY + STREAMER_LIFE).toBeLessThanOrEqual(1.6);
    expect(SPARK_EVERY * (SPARKS_MAX - 1) + SPARK_LIFE).toBeLessThanOrEqual(1.6);
    expect(SUNRISE_LIFE).toBeLessThanOrEqual(1.6);
    expect(sparks(BOX, 30, '#0a0')).toHaveLength(12);
    expect(sparks(BOX, 3, '#0a0').map((s) => s.age)).toEqual([-SPARK_DELAY, -(SPARK_DELAY + SPARK_EVERY), -(SPARK_DELAY + 2 * SPARK_EVERY)]);
  });
});

describe("seasonal touches change only the streamers' palette and shape", () => {
  it('snow in December, leaves in October and November, fireworks on January 1', () => {
    expect(season(new Date(2026, 11, 3))).toBe('snow');
    expect(season(new Date(2026, 9, 28))).toBe('leaves');
    expect(season(new Date(2026, 10, 30))).toBe('leaves');
    expect(season(new Date(2027, 0, 1))).toBe('fireworks');
    expect(season(new Date(2027, 0, 2))).toBeNull();
    expect(SUMMER).toEqual({ colors: ['#123'], shape: 'ribbon' });
    expect(look(new Date(2026, 11, 3), ['#123']).shape).toBe('flake');
    const motion = (ps: Particle[]) => ps.map(({ x, y, vx, vy, g, life, age }) => ({ x, y, vx, vy, g, life, age }));
    expect(motion(streamers(BOX, look(new Date(2026, 11, 3), ['#123']), 4, () => 0.5))).toEqual(motion(streamers(BOX, SUMMER, 4, () => 0.5)));
  });
});
