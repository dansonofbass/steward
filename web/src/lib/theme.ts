import { PHASE_BG, phaseFor, type Phase } from './sky';

// "Follow the sky" (default; its dark half when the device is set to dark), Light (= the day phase) or Dark (= the night
// phase). Stored per device.
export type Theme = 'sky' | 'light' | 'dark';
const KEY = 'steward-theme';

export function getTheme(): Theme {
  try {
    const t = localStorage.getItem(KEY);
    return t === 'light' || t === 'dark' ? t : 'sky';
  } catch {
    return 'sky';
  }
}

/** "Follow the sky" on a device set to dark (WEB-10): each light phase gives way to the nearest dark one, the morning's
 *  to dawn and the afternoon's to dusk, so the sky still moves but never turns cream. index.html's first-paint script
 *  maps it the same way. */
export const DARK_SKY: Record<Phase, Phase> = {
  night: 'night', dawn: 'dawn', sunrise: 'dawn', morning: 'dawn', day: 'dusk', afternoon: 'dusk', evening: 'dusk', dusk: 'dusk',
};
const DARK_QUERY = '(prefers-color-scheme: dark)';
const prefersDark = () => typeof window !== 'undefined' && window.matchMedia?.(DARK_QUERY).matches === true;

export function phaseOf(t: Theme, now: Date = new Date(), dark: boolean = prefersDark()): Phase {
  if (t === 'light') return 'day';
  if (t === 'dark') return 'night';
  return dark ? DARK_SKY[phaseFor(now)] : phaseFor(now);
}

/** Sets <html data-phase>, which sky.css turns into the colour tokens, and the browser bar's colour to that phase's
 *  ground: the phase on screen, not the phone's own light or dark setting (phase 17, spec 2.6). */
export function applyTheme(t: Theme = getTheme()) {
  const phase = phaseOf(t);
  document.documentElement.dataset.phase = phase;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', PHASE_BG[phase]);
}

export function setTheme(t: Theme) {
  try {
    if (t === 'sky') localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, t);
  } catch {
    /* private mode */
  }
  applyTheme(t);
}

/** Keeps the phase current while the page is open: every minute, whenever the tab comes back, and when the device
 *  switches between light and dark. Returns a stop function. */
export function followSky(): () => void {
  applyTheme();
  const tick = () => applyTheme();
  const onVisible = () => { if (document.visibilityState === 'visible') tick(); };
  const id = window.setInterval(tick, 60_000);
  document.addEventListener('visibilitychange', onVisible);
  const scheme = window.matchMedia?.(DARK_QUERY);
  scheme?.addEventListener('change', tick);
  return () => {
    window.clearInterval(id);
    document.removeEventListener('visibilitychange', onVisible);
    scheme?.removeEventListener('change', tick);
  };
}
