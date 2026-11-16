// Phase 17 (spec 2.5): each seasonal look has a light and a dark palette, so November's leaves read on navy and
// December's snow on light paper. 3:1 is the chart-mark target, on every ground of the theme.
import { describe, expect, it } from 'vitest';
import { DARK_PHASES, PHASE_BG, PHASES } from '../lib/sky';
import { contrast } from '../test-colour';
import { look, PALETTES, seasonColors, type Season } from './season';

const DARK_GROUNDS = PHASES.filter((p) => DARK_PHASES.has(p)).map((p) => PHASE_BG[p]);
const LIGHT_GROUNDS = [...PHASES.filter((p) => !DARK_PHASES.has(p)).map((p) => PHASE_BG[p]), '#FFFFFF'];
const SEASONS: Season[] = ['snow', 'leaves', 'fireworks'];

describe('seasons in both themes (phase 17, 2.5)', () => {
  it('every dark palette reads at 3:1 on every dark ground', () => {
    for (const s of SEASONS) for (const c of PALETTES[s].dark) for (const g of DARK_GROUNDS)
      expect(contrast(c, g), `${s} ${c} on ${g}`).toBeGreaterThanOrEqual(3);
  });

  it('the light snow reads at 3:1 on every light ground and on a white card', () => {
    for (const c of PALETTES.snow.light) for (const g of LIGHT_GROUNDS)
      expect(contrast(c, g), `snow ${c} on ${g}`).toBeGreaterThanOrEqual(3);
  });

  it('the light leaves and fireworks are the colours they always had', () => {
    expect(PALETTES.leaves.light).toEqual(['#C8553D', '#E09F3E', '#9E4A2B', '#B9772E']);
    expect(PALETTES.fireworks.light).toEqual(['#FF4D6D', '#FFD60A', '#4CC9F0', '#9B5DE5', '#80ED99']);
  });

  it("seasonColors gives the theme's palette", () => {
    for (const s of SEASONS) {
      expect(seasonColors(s, true)).toBe(PALETTES[s].dark);
      expect(seasonColors(s, false)).toBe(PALETTES[s].light);
    }
  });

  it('look() turns on the date and the theme: leaves to Nov 30, snow from Dec 1, fireworks on Jan 1 only', () => {
    expect(look(new Date(2026, 10, 30, 23, 59), ['#123'], true)).toEqual({ colors: PALETTES.leaves.dark, shape: 'leaf' });
    expect(look(new Date(2026, 11, 1, 0, 0), ['#123'], false)).toEqual({ colors: PALETTES.snow.light, shape: 'flake' });
    expect(look(new Date(2027, 0, 1, 9), ['#123'], true)).toEqual({ colors: PALETTES.fireworks.dark, shape: 'ribbon' });
    expect(look(new Date(2027, 0, 2, 9), ['#123'], true)).toEqual({ colors: ['#123'], shape: 'ribbon' });
    expect(look(new Date(2026, 10, 3), ['#123']).colors).toBe(PALETTES.leaves.light);   // dark defaults to false
  });
});
