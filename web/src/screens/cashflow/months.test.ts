import { describe, expect, it } from 'vitest';
import type { FlowMonth } from '../../api/types';
import { drillHref, fromFirstData, monthLong, monthRange, monthReadout, monthShort, monthTitle, stripBars } from './months';

const m = (month: string, net: number): FlowMonth => ({ month, in_cents: Math.max(net, 0), out_cents: Math.max(-net, 0), net_cents: net });

describe('month helpers', () => {
  it('names months', () => {
    expect(monthShort('2026-09')).toBe('Sep');
    expect(monthLong('2026-09')).toBe('September 2026');
    expect(monthTitle('2026-09', '2026-10-14')).toBe('September 2026');
    expect(monthTitle('2026-10', '2026-10-14')).toBe('October 2026 so far');
  });
  it('gives a full month, or the month so far', () => {
    expect(monthRange('2026-09', '2026-10-14')).toEqual({ from: '2026-09-01', to: '2026-09-30' });
    expect(monthRange('2024-02', '2026-10-14')).toEqual({ from: '2024-02-01', to: '2024-02-29' });
    expect(monthRange('2026-10', '2026-10-14')).toEqual({ from: '2026-10-01', to: '2026-10-14' });
  });
  it('links a category to Transactions for that month', () => {
    expect(drillHref('2026-09', 'groceries', '2026-10-14')).toBe('/transactions?category=groceries&dates=custom&from=2026-09-01&to=2026-09-30');
  });
  it('draws one difference bar per month above or below a shared line', () => {
    const { axis, bars } = stripBars([m('2026-08', 3000), m('2026-09', -1000), m('2026-10', 0)], '2026-10-14');
    expect(axis).toBe(32);
    expect(bars[0]).toEqual({ x: 3.5, y: 2, w: 93, h: 30, cls: 'in' });
    expect(bars[1]).toEqual({ x: 103.5, y: 32, w: 93, h: 10, cls: 'out' });
    expect(bars[2]).toEqual({ x: 203.5, y: 30, w: 93, h: 2, cls: 'in so-far' });
  });
  it('centres the line when nothing moved', () => {
    expect(stripBars([m('2026-09', 0), m('2026-10', 0)], '2026-10-14').axis).toBe(22);
  });
});

describe('the hover readout (sorting redesign, Home)', () => {
  it('names the month with its income, spending and the difference, and marks the current one so far', () => {
    expect(monthReadout({ month: '2026-09', in_cents: 820000, out_cents: 690000, net_cents: 130000 }, '2026-10-14'))
      .toBe('September: Income $8,200 · Spending $6,900 · +$1,300');
    expect(monthReadout({ month: '2026-10', in_cents: 300000, out_cents: 410000, net_cents: -110000 }, '2026-10-14'))
      .toBe('October so far: Income $3,000 · Spending $4,100 · −$1,100');
  });

  it('names the year for a month outside the current one, so last December never reads as next month (#34)', () => {
    expect(monthReadout({ month: '2025-12', in_cents: 0, out_cents: 0, net_cents: 0 }, '2026-11-16'))
      .toBe('December 2025: Income $0 · Spending $0 · $0');
    expect(monthReadout({ month: '2026-01', in_cents: 100, out_cents: 0, net_cents: 100 }, '2026-11-16')).toMatch(/^January: /);
  });
});

describe('the months the strip shows (#34)', () => {
  it('leaves out the empty months before the first money in or out, and keeps the quiet ones after it', () => {
    const months = [m('2025-12', 0), m('2026-01', 0), m('2026-02', 500), m('2026-03', 0), m('2026-04', -200)];
    expect(fromFirstData(months).map((x) => x.month)).toEqual(['2026-02', '2026-03', '2026-04']);
  });
  it('keeps the current month when nothing came in or went out yet', () => {
    expect(fromFirstData([m('2026-10', 0), m('2026-11', 0)]).map((x) => x.month)).toEqual(['2026-11']);
    expect(fromFirstData([])).toEqual([]);
  });
});
