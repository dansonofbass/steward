import { describe, expect, it } from 'vitest';
import { bandGeometry, bandWords, millions, niceStep, shortMoney, spreadLabels, thin } from './band';
import { planFixture } from './fixtures';

describe('band chart helpers', () => {
  it('picks round steps and short labels', () => {
    expect(niceStep(800_000_000)).toBe(300_000_000);
    expect(niceStep(600_000_000)).toBe(200_000_000);
    expect(shortMoney(400_000_000)).toBe('$4M');
    expect(shortMoney(50_000_000)).toBe('$500k');
    expect(millions(240_000_000)).toBe('$2.4 million');
    expect(millions(85_000_000)).toBe('$850,000');
  });
  it('draws the band inside the box with $0 at the bottom', () => {
    const g = bandGeometry(planFixture().result.band, 300, 180);
    expect(g.x(41)).toBe(0);
    expect(g.x(97)).toBe(300);
    expect(g.ticks[0]).toEqual({ y: 180, label: '$0' });
    expect(g.ticks.at(-1)!.label).toBe('$9M');
    expect(g.mid.split(' ')).toHaveLength(6);
  });
  it('keeps the end labels apart', () => {
    expect(spreadLabels([20, 25, 170], 14)).toEqual([20, 34, 170]);
  });
  it('says what the chart shows in words', () => {
    const { band } = planFixture().result;
    expect(bandWords(band, 63, 'Sam', 'JR')).toBe("Retiring at 63, in a typical market you'd have about $2.4 million left when Sam is 95. In a rough market it gets close to $0 but does not run out.");
    const broke = band.map((p) => (p.jr_age >= 77 ? { ...p, p10_cents: 0 } : p));
    expect(bandWords(broke, 63, 'Sam', 'JR')).toContain('In a rough market the money runs out when JR is about 77.');
  });
  it('thins a long series and keeps the ends', () => {
    const t = thin(Array.from({ length: 3650 }, (_, i) => i), 120);
    expect(t.length).toBeLessThanOrEqual(121);
    expect(t[0]).toBe(0);
    expect(t.at(-1)).toBe(3649);
  });
});
