import { beforeEach, describe, expect, it, vi } from 'vitest';

type Note = { freq: number; start: number; stop: number };
let notes: Note[];
class FakeAudio {
  currentTime = 0;
  destination = {};
  resume() { return Promise.resolve(); }
  createGain() { return { gain: { setValueAtTime: () => {}, exponentialRampToValueAtTime: () => {} }, connect: (x: unknown) => x }; }
  createOscillator() {
    const n: Note = { freq: 0, start: -1, stop: -1 };
    notes.push(n);
    return { type: 'sine', frequency: { set value(v: number) { n.freq = v; } }, connect: (g: unknown) => g,
      start: (t: number) => { n.start = t; }, stop: (t: number) => { n.stop = t; } };
  }
}
beforeEach(() => { notes = []; vi.resetModules(); vi.stubGlobal('AudioContext', FakeAudio); });

describe('the two sounds (phase 17 spec 3.8)', () => {
  it('the ding is unchanged: 880 Hz then 1318.5 Hz', async () => {
    const { ding } = await import('./sound');
    ding();
    expect(notes.map((n) => n.freq)).toEqual([880, 1318.5]);
  });

  it('the golden chime is distinct and brighter, and done within half a second', async () => {
    const { chime } = await import('./sound');
    chime();
    expect(notes.map((n) => n.freq)).toEqual([1046.5, 1318.5, 1568]);
    expect(Math.max(...notes.map((n) => n.stop))).toBeLessThanOrEqual(0.5);
    expect(Math.min(...notes.map((n) => n.freq))).toBeGreaterThan(880);
  });

  it('without Web Audio nothing plays and nothing throws', async () => {
    vi.stubGlobal('AudioContext', undefined);
    const { chime } = await import('./sound');
    expect(() => chime()).not.toThrow();
  });
});
