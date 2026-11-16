import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { TrendRow } from '../../api/types';
import { TrendBars } from './TrendBars';

const MONTHS = ['2026-05', '2026-06', '2026-07', '2026-08', '2026-09', '2026-10'];
const row = (o: Partial<TrendRow>): TrendRow =>
  ({ category: 'dining', kind: 'everyday', group: 'everyday', target_cents: 50_000, expected_cents: null, typical_cents: null, spent: [1, 2, 3, 4, 5, 6].map((n) => n * 10_000), over_in: 0, over_of: 6, order: 0, ...o });
const draw = (r: TrendRow) => render(<TrendBars row={r} months={MONTHS} current="2026-10" />).container;
const inside = (c: HTMLElement) => {
  const [, , w, h] = c.querySelector('svg')!.getAttribute('viewBox')!.split(' ').map(Number);
  for (const b of c.querySelectorAll('rect')) {
    const [x, y, bw, bh] = ['x', 'y', 'width', 'height'].map((a) => Number(b.getAttribute(a)));
    expect(y).toBeGreaterThanOrEqual(0);
    expect(y + bh).toBeLessThanOrEqual(h + 0.1);
    expect(x).toBeGreaterThanOrEqual(0);
    expect(x + bw).toBeLessThanOrEqual(w);
    expect(bh).toBeGreaterThanOrEqual(0);
  }
};

describe('TrendBars', () => {
  it('draws the dashed target line for a targeted row, and a label under each bar as HTML', () => {
    const c = draw(row({}));
    expect(c.querySelectorAll('line.sp-chart__target')).toHaveLength(1);
    expect(c.querySelectorAll('svg text')).toHaveLength(0);
    expect([...c.querySelectorAll('.sp-chart__month')].map((e) => e.textContent)).toEqual(['M', 'J', 'J', 'A', 'S', 'so far']);
  });
  it('draws every bar flat and inside the box when every month is $0', () => {
    const c = draw(row({ spent: [0, 0, 0, 0, 0, 0] }));
    expect(c.querySelectorAll('rect')).toHaveLength(6);
    inside(c);
  });
  it('draws no line without a target, and keeps bars inside the box for a target of 0', () => {
    expect(draw(row({ target_cents: null })).querySelector('line.sp-chart__target')).toBeNull();
    const c = draw(row({ target_cents: 0 }));
    inside(c);
    expect(c.querySelectorAll('rect.is-over').length).toBeGreaterThan(0);
  });
  it('keeps an outlier and a negative month inside the box', () => {
    const c = draw(row({ spent: [-5_000, 1_000, 9_000_000, 1_000, 0, 2_000] }));
    inside(c);
    expect(c.querySelectorAll('rect')).toHaveLength(6);
  });
});
