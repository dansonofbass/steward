import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useFakeTimers } from '../test-clock';
import { phaseFor } from './sky';
import { DARK_SKY, followSky, phaseOf, setTheme } from './theme';

const at = (hh: number, mm = 0) => new Date(2026, 9, 13, hh, mm);

describe('phaseFor', () => {
  it('maps the clock to the eight bands', () => {
    expect(phaseFor(at(3))).toBe('night');
    expect(phaseFor(at(5, 30))).toBe('dawn');
    expect(phaseFor(at(12))).toBe('day');
    expect(phaseFor(at(19))).toBe('evening');
    expect(phaseFor(at(20, 30))).toBe('dusk');
  });
  it('uses half-open bands', () => {
    expect(phaseFor(at(4, 59))).toBe('night');
    expect(phaseFor(at(6))).toBe('sunrise');
    expect(phaseFor(at(7))).toBe('morning');
    expect(phaseFor(at(15))).toBe('afternoon');
    expect(phaseFor(at(21))).toBe('night');
  });
});

describe('setTheme', () => {
  afterEach(() => { vi.useRealTimers(); localStorage.clear(); });
  it('pins dark to night and light to day, and sky follows the clock', () => {
    useFakeTimers();
    vi.setSystemTime(at(12));
    setTheme('dark');
    expect(document.documentElement.dataset.phase).toBe('night');
    expect(localStorage.getItem('steward-theme')).toBe('dark');
    setTheme('light');
    expect(document.documentElement.dataset.phase).toBe('day');
    vi.setSystemTime(at(3));
    setTheme('sky');
    expect(document.documentElement.dataset.phase).toBe('night');
    expect(localStorage.getItem('steward-theme')).toBeNull();
  });
  it('re-applies the phase every minute while following the sky', () => {
    useFakeTimers();
    vi.setSystemTime(at(19, 59));
    setTheme('sky');
    const stop = followSky();
    expect(document.documentElement.dataset.phase).toBe('evening');
    vi.advanceTimersByTime(60_000);
    expect(document.documentElement.dataset.phase).toBe('dusk');
    stop();
  });
  it('re-applies the phase when the tab becomes visible again', () => {
    useFakeTimers();
    vi.setSystemTime(at(12));
    setTheme('sky');
    const stop = followSky();
    expect(document.documentElement.dataset.phase).toBe('day');
    vi.setSystemTime(at(19)); // the clock moved while the tab was hidden; no interval tick has fired
    document.dispatchEvent(new Event('visibilitychange'));
    expect(document.documentElement.dataset.phase).toBe('evening');
    stop();
  });
});

describe("Follow the sky on a device set to dark (WEB-10)", () => {
  /** A matchMedia whose dark setting the test turns, with its change listeners. */
  function device(dark: boolean) {
    const listeners = new Set<() => void>();
    const mq = { get matches() { return dark; }, addEventListener: (_: string, f: () => void) => listeners.add(f),
      removeEventListener: (_: string, f: () => void) => listeners.delete(f) };
    vi.stubGlobal('matchMedia', vi.fn((q: string) => (q === '(prefers-color-scheme: dark)' ? mq : { matches: false, addEventListener() {}, removeEventListener() {} })));
    return { turn(to: boolean) { dark = to; listeners.forEach((f) => f()); }, listeners };
  }
  afterEach(() => { vi.useRealTimers(); localStorage.clear(); });

  it("each light phase gives way to the nearest dark one; the dark ones stay", () => {
    expect(Object.entries(DARK_SKY)).toEqual([
      ['night', 'night'], ['dawn', 'dawn'], ['sunrise', 'dawn'], ['morning', 'dawn'],
      ['day', 'dusk'], ['afternoon', 'dusk'], ['evening', 'dusk'], ['dusk', 'dusk'],
    ]);
    expect(phaseOf('sky', at(13), true)).toBe('dusk');
    expect(phaseOf('sky', at(8), true)).toBe('dawn');
    expect(phaseOf('sky', at(13), false)).toBe('day');
  });

  it('Light and Dark are chosen, so they stay what they say', () => {
    expect(phaseOf('light', at(13), true)).toBe('day');
    expect(phaseOf('dark', at(13), false)).toBe('night');
  });

  it('a phone in dark mode at 1 pm gets the dark sky, and turning it light brings the day back at once', () => {
    useFakeTimers();
    vi.setSystemTime(at(13));
    const phone = device(true);
    setTheme('sky');
    const stop = followSky();
    expect(document.documentElement.dataset.phase).toBe('dusk');
    phone.turn(false);
    expect(document.documentElement.dataset.phase).toBe('day');
    stop();
    expect(phone.listeners.size).toBe(0);
  });
});

describe('the browser bar (phase 17, spec 2.6)', () => {
  beforeEach(() => { document.head.innerHTML = '<meta name="theme-color" content="#FAF8F3">'; });
  afterEach(() => { vi.useRealTimers(); localStorage.clear(); document.head.innerHTML = ''; });
  const bar = () => document.querySelector('meta[name="theme-color"]')?.getAttribute('content');

  it("follows the chosen theme, not the phone's setting", () => {
    useFakeTimers();
    vi.setSystemTime(at(12));
    setTheme('dark');
    expect(bar()).toBe('#0E1729');
    setTheme('light');
    expect(bar()).toBe('#FAF8F3');
    vi.setSystemTime(at(20, 30));
    setTheme('sky');
    expect(bar()).toBe('#2A3144');     // dusk
  });

  it('moves with the sky while the page stays open', () => {
    useFakeTimers();
    vi.setSystemTime(at(20, 59));
    setTheme('sky');
    const stop = followSky();
    expect(bar()).toBe('#2A3144');     // dusk
    vi.advanceTimersByTime(60_000);
    expect(bar()).toBe('#0E1729');     // 21:00, night
    stop();
  });
});
