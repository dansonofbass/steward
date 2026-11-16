// The eight sky phases (mirrored from the sky clock's clock.js), chosen by fixed hour bands on the device clock.
export const PHASES = ['night', 'dawn', 'sunrise', 'morning', 'day', 'afternoon', 'evening', 'dusk'] as const;
export type Phase = (typeof PHASES)[number];

/** The dark phases: sky.css gives exactly these color-scheme: dark (styles/sky.contrast.test.ts holds the two together). */
export const DARK_PHASES: ReadonlySet<Phase> = new Set<Phase>(['night', 'dawn', 'dusk']);
export const isDarkPhase = (p: string | undefined): boolean => DARK_PHASES.has(p as Phase);

/** Each phase's page ground (sky.css --bg), for the browser bar's theme-color (phase 17, spec 2.6). index.html's
 *  first-paint script repeats it; indexHtml.test.ts holds the three together. */
export const PHASE_BG: Record<Phase, string> = {
  night: '#0E1729', dawn: '#2D3A54', sunrise: '#FBEDDF', morning: '#F9F7F3', day: '#FAF8F3', afternoon: '#F8F2E6', evening: '#F8E4CD', dusk: '#2A3144',
};

// Half-open local-time bands [from, to): night 21–5, dawn 5–6, sunrise 6–7, morning 7–11, day 11–15,
// afternoon 15–18, evening 18–20, dusk 20–21. index.html's first-paint script repeats these bands.
export function phaseFor(date: Date): Phase {
  const h = date.getHours();
  if (h < 5) return 'night';
  if (h < 6) return 'dawn';
  if (h < 7) return 'sunrise';
  if (h < 11) return 'morning';
  if (h < 15) return 'day';
  if (h < 18) return 'afternoon';
  if (h < 20) return 'evening';
  if (h < 21) return 'dusk';
  return 'night';
}
