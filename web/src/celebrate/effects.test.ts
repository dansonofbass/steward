// Phase 17 (spec 2.5): the sunrise fades to a transparent version of its own hue, never to transparent white (which
// turned its outer ring to grey fog on navy).
import { describe, expect, it } from 'vitest';
import { clear, sunrise } from './effects';

describe('the sunrise fades to its own hue (phase 17, 2.5)', () => {
  it('clear() is the colour at no opacity', () => {
    expect(clear('#E8B04B')).toBe('rgba(232, 176, 75, 0)');
    expect(clear(' #8dc49a ')).toBe('rgba(141, 196, 154, 0)');
  });

  it('its outer stop is the warm colour, cleared', () => {
    const stops: [number, string][] = [];
    const ctx = {
      createRadialGradient: () => ({ addColorStop: (o: number, c: string) => { stops.push([o, c]); } }),
      beginPath() {}, arc() {}, fill() {}, globalAlpha: 1, fillStyle: '',
    } as unknown as CanvasRenderingContext2D;
    const box = { left: 0, top: 0, right: 200, bottom: 40, width: 200, height: 40 } as DOMRect;
    sunrise(box, ['#8DC49A', '#E8B04B']).draw(ctx, 0.3);
    expect(stops).toEqual([[0, '#8DC49A'], [0.55, '#E8B04B'], [1, 'rgba(232, 176, 75, 0)']]);
  });
});
