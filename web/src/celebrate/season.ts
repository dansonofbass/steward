import type { Shape } from './engine';
import { season } from '../lib/season';

export { season };

export type Look = { colors: readonly string[]; shape: Shape };
export type Season = 'snow' | 'leaves' | 'fireworks';

/** Phase 17 (spec 2.5): each look in a light and a dark palette, so the leaves read on navy and the snow on light paper
 *  (season.test.ts holds each to 3:1 on its theme's grounds). The light leaves and fireworks are the colours they always
 *  had. */
export const PALETTES: Record<Season, { light: readonly string[]; dark: readonly string[] }> = {
  snow: { light: ['#5E7FA3', '#4A6A8E', '#54749A'], dark: ['#FFFFFF', '#E3ECF5', '#C9D8E8'] },
  leaves: { light: ['#C8553D', '#E09F3E', '#9E4A2B', '#B9772E'], dark: ['#F08A5D', '#F2B85B', '#E8734F', '#F5A34A'] },
  fireworks: { light: ['#FF4D6D', '#FFD60A', '#4CC9F0', '#9B5DE5', '#80ED99'], dark: ['#FF6B85', '#FFD60A', '#4CC9F0', '#B48AF0', '#80ED99'] },
};
const SHAPES: Record<Season, Shape> = { snow: 'flake', leaves: 'leaf', fireworks: 'ribbon' };

export function seasonColors(s: Season, dark: boolean): readonly string[] {
  return dark ? PALETTES[s].dark : PALETTES[s].light;
}

/** The streamers' look on `now`, in the theme on screen (`dark`: a dark sky phase). */
export function look(now: Date, base: readonly string[], dark = false): Look {
  const s = season(now);
  return s ? { colors: seasonColors(s, dark), shape: SHAPES[s] } : { colors: base, shape: 'ribbon' };
}
