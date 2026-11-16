import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useFakeTimers } from '../test-clock';

const fx = vi.hoisted(() => ({
  ding: vi.fn(),
  add: vi.fn((_ps: { shape: string }[]) => {}),
  addDrawer: vi.fn((_d: { life: number }) => {}),
}));
vi.mock('./sound', () => ({ ding: fx.ding, chime: vi.fn() }));
vi.mock('./engine', async (orig) => ({ ...(await orig<typeof import('./engine')>()), engine: { add: fx.add, addDrawer: fx.addDrawer, capacity: () => 40 } }));

import {
  burst, BURST_MS, closer, CLOSER_STREAMERS, pop, POP_MS, quiet, sorted, square, STAMP_DELAY_MS, STAMP_LANDS_MS,
  profile, STAMP_MS, sunrise, trip, winMoment,
} from './celebrate';
import { MOMENT_DELAY_MS } from './moments';
import { PALETTES } from './season';

const card = () => document.body.appendChild(document.createElement('article'));
beforeEach(() => { Object.defineProperty(navigator, 'vibrate', { configurable: true, value: vi.fn() }); });
afterEach(() => { vi.clearAllMocks(); document.body.innerHTML = ''; });

describe('the celebrate chunk (sorting redesign, Moments and order)', () => {
  it('a sort: the SORTED stamp, a haptic tick, streamers and a spark per matching row up to 12, the moment, and the ding only with Sound', () => {
    useFakeTimers();
    const el = card();
    const off = sorted({ card: el, category: 'transport', applied: 30, sound: false, now: new Date(2027, 6, 4) });
    expect(el.querySelector('.cel-stamp')).toHaveTextContent('SORTED');
    vi.advanceTimersByTime(BURST_MS);
    expect(el.querySelector('.cel-moment svg')).not.toBeNull();
    expect(navigator.vibrate).toHaveBeenCalledWith(12);
    expect(fx.ding).not.toHaveBeenCalled();
    const ps = fx.add.mock.calls[0][0];
    expect(ps).toHaveLength(40);
    expect(ps.filter((p) => p.shape === 'spark')).toHaveLength(12);
    off();
    expect(el.querySelector('.cel-stamp')).toBeNull();
    expect(el.querySelector('.cel-moment')).toBeNull();
    sorted({ card: card(), category: 'dining', applied: 0, sound: true });
    vi.advanceTimersByTime(STAMP_LANDS_MS);
    expect(fx.ding).toHaveBeenCalledOnce();
    vi.useRealTimers();
  });

  it("in a dark phase the season's dark palette streams (phase 17, 2.5)", () => {
    useFakeTimers();
    document.documentElement.dataset.phase = 'night';
    sorted({ card: card(), category: 'transport', applied: 0, sound: false, now: new Date(2026, 10, 10) });
    vi.advanceTimersByTime(BURST_MS);
    const ps = fx.add.mock.calls[0][0] as unknown as { color: string; shape: string }[];
    expect(ps.length).toBeGreaterThan(0);
    for (const p of ps) { expect(p.shape).toBe('leaf'); expect(PALETTES.leaves.dark).toContain(p.color); }
    delete document.documentElement.dataset.phase;
  });

  it('paces a sort so the receipt reads first: the stamp at about 280 ms, then the burst as it settles, sparks last', () => {
    useFakeTimers();
    const animate = vi.fn((_f: Keyframe[], _o?: KeyframeAnimationOptions) => ({ finished: Promise.resolve() }));
    Object.defineProperty(HTMLElement.prototype, 'animate', { configurable: true, value: animate });
    try {
      const el = card();
      const slot = el.appendChild(document.createElement('span'));
      sorted({ card: el, stamp: slot, category: 'transport', applied: 3, sound: true });
      // The stamp goes in the receipt's place for it, hidden until its delay, transform and opacity only.
      const s = slot.querySelector('.cel-stamp')!;
      expect(s).not.toBeNull();
      expect(el.querySelector(':scope > .cel-stamp')).toBeNull();
      const [frames, opts] = animate.mock.calls[0];
      expect(new Set(frames.flatMap((f) => Object.keys(f).filter((k) => k !== 'offset')))).toEqual(new Set(['transform', 'opacity']));
      expect(opts).toMatchObject({ delay: STAMP_DELAY_MS, duration: STAMP_MS, fill: 'backwards' });
      expect(STAMP_DELAY_MS).toBeGreaterThanOrEqual(250);
      expect(STAMP_DELAY_MS).toBeLessThanOrEqual(300);
      expect(STAMP_MS).toBe(450);
      // Nothing else before the stamp lands: then the tick and the ding.
      vi.advanceTimersByTime(STAMP_LANDS_MS - 1);
      expect(navigator.vibrate).not.toHaveBeenCalled();
      expect(fx.ding).not.toHaveBeenCalled();
      vi.advanceTimersByTime(1);
      expect(navigator.vibrate).toHaveBeenCalledWith(12);
      expect(fx.ding).toHaveBeenCalledOnce();
      // The burst as the stamp settles: streamers and the moment start after the stamp, the sparks after them.
      vi.advanceTimersByTime(BURST_MS - STAMP_LANDS_MS - 1);
      expect(fx.add).not.toHaveBeenCalled();
      expect(el.querySelector('.cel-moment')).toBeNull();
      vi.advanceTimersByTime(1);
      const ps = fx.add.mock.calls[0][0] as unknown as { shape: string; age: number; life: number }[];
      const startOf = (p: { age: number }) => BURST_MS - p.age * 1000;
      const streamersAt = Math.min(...ps.filter((p) => p.shape !== 'spark').map(startOf));
      const sparksAt = Math.min(...ps.filter((p) => p.shape === 'spark').map(startOf));
      expect(streamersAt).toBeGreaterThanOrEqual(STAMP_DELAY_MS + STAMP_MS);
      expect(BURST_MS + MOMENT_DELAY_MS).toBeGreaterThanOrEqual(STAMP_DELAY_MS + STAMP_MS);
      expect(sparksAt).toBeGreaterThan(streamersAt);
      expect(el.querySelector('.cel-moment')).not.toBeNull();
    } finally {
      delete (HTMLElement.prototype as { animate?: unknown }).animate;
      vi.useRealTimers();
    }
  });

  it('Undo before the burst takes off the stamp and cancels what has not started', () => {
    useFakeTimers();
    const el = card();
    const off = sorted({ card: el, category: 'transport', applied: 3, sound: true });
    off();
    vi.advanceTimersByTime(2000);
    expect(el.querySelector('.cel-stamp')).toBeNull();
    expect(el.querySelector('.cel-moment')).toBeNull();
    expect(fx.add).not.toHaveBeenCalled();
    expect(fx.ding).not.toHaveBeenCalled();
    expect(navigator.vibrate).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it('Snooze and Ignore: only the stamp (LATER, OK); no tick, no ding, no streamers', () => {
    quiet({ card: card(), kind: 'snooze' });
    quiet({ card: card(), kind: 'ignore' });
    expect([...document.querySelectorAll('.cel-stamp')].map((s) => s.textContent)).toEqual(['LATER', 'OK']);
    expect(navigator.vibrate).not.toHaveBeenCalled();
    expect(fx.ding).not.toHaveBeenCalled();
    expect(fx.add).not.toHaveBeenCalled();
  });

  it('in the list a sort marks nothing (the slim row has its own tag); after a swipe it skips the landing tick', () => {
    useFakeTimers();
    const el = card();
    sorted({ card: el, category: 'transport', applied: 0, sound: false, mark: false, tick: false });
    expect(el.querySelector('.cel-stamp')).toBeNull();
    vi.advanceTimersByTime(BURST_MS);
    expect(navigator.vibrate).not.toHaveBeenCalled();
    expect(el.querySelector('.cel-moment svg')).not.toBeNull();       // the moment still plays
    vi.useRealTimers();
  });

  it('pops Ten in a row or a milestone, said to screen readers; the sunrise is one drawer of 1.6 s', () => {
    pop('Ten in a row');
    expect(document.querySelector('.cel-pop')).toHaveTextContent('Ten in a row');
    expect(document.querySelector('.cel-pop')).toHaveAttribute('role', 'status');
    sunrise(card());
    expect(fx.addDrawer.mock.calls[0][0].life).toBe(1.6);
    expect(Math.max(STAMP_MS, POP_MS)).toBeLessThanOrEqual(1600);
  });

  it('all square: streamers and the coins, no stamp; marking a trip: the plane, once (reimbursable spec, Joy)', () => {
    const host = card();
    square({ host });
    expect(host.querySelector('.cel-stamp')).toBeNull();
    expect(host.querySelectorAll('.cel-moment ellipse')).toHaveLength(3);
    expect(fx.add).toHaveBeenCalledOnce();
    expect(navigator.vibrate).not.toHaveBeenCalled();
    const t = card();
    trip({ host: t });
    expect(t.querySelectorAll('.cel-moment')).toHaveLength(1);
    expect(t.querySelector('.cel-moment ellipse')).toBeNull();
    expect(t.querySelector('.cel-moment path')).not.toBeNull();
    expect(fx.add).toHaveBeenCalledOnce();          // the plane alone: no streamers
  });

  it("the Plan's change line: a small burst of streamers from the line, and no stamp, tick or ding (plan subpages decision 7)", () => {
    const el = card();
    closer({ over: el, now: new Date(2027, 6, 4) });
    const ps = fx.add.mock.calls[0][0];
    expect(ps).toHaveLength(CLOSER_STREAMERS);
    expect(ps.some((p) => p.shape === 'spark')).toBe(false);
    expect(el.querySelector('.cel-stamp')).toBeNull();
    expect(navigator.vibrate).not.toHaveBeenCalled();
    expect(fx.ding).not.toHaveBeenCalled();
  });

  it('a milestone, a limit reached or a first import: a small burst from the element, and no stamp, tick or ding (investment views spec)', () => {
    const el = card();
    burst({ over: el, now: new Date(2027, 6, 4) });
    const ps = fx.add.mock.calls[0][0];
    expect(ps).toHaveLength(CLOSER_STREAMERS);
    expect(el.querySelector('.cel-stamp')).toBeNull();
    expect(navigator.vibrate).not.toHaveBeenCalled();
    expect(fx.ding).not.toHaveBeenCalled();
  });

  it('profile plays the kids or the home moment over its host, and 5 of 5 a burst; each can be taken off', () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const off = profile({ host, kind: 'kids' });
    expect(host.querySelector('.cel-moment.cel-moment--row')).not.toBeNull();   // over the row's icon, clear of its summary
    off();
    expect(host.querySelector('.cel-moment')).toBeNull();
    expect(() => profile({ host, kind: 'all' })()).not.toThrow();
  });

  it('a win moment (phase 17): the coins or the sprout over the host, and the ding only with Sound', () => {
    useFakeTimers();
    const el = card();
    const off = winMoment({ host: el, name: 'coins' });
    expect(el.querySelector('.cel-moment svg')).not.toBeNull();
    expect(fx.ding).not.toHaveBeenCalled();
    off();
    expect(el.querySelector('.cel-moment')).toBeNull();
    winMoment({ host: el, name: 'sprout', sound: true });
    expect(fx.ding).toHaveBeenCalledOnce();
  });
});
