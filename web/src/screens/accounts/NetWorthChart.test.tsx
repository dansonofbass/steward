import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { stubFetch, wrap } from '../../test-utils';
import NetWorthChart from './NetWorthChart';

afterEach(() => vi.unstubAllGlobals());

const media = (wide: boolean) => vi.stubGlobal('matchMedia', (q: string) => ({ matches: wide, media: q, addEventListener: () => {}, removeEventListener: () => {} }));

const day = (y: number, m: number) => `${y}-${String(m).padStart(2, '0')}-15`;

describe('NetWorthChart', () => {
  it('starts at the first balance, not at the zero-filled years before it', async () => {
    const zeros = Array.from({ length: 24 }, (_, i) => ({ date: day(2022 + Math.floor(i / 12), (i % 12) + 1), net_worth_cents: 0 }));
    const real = [
      { date: day(2024, 3), net_worth_cents: 150_000_000 },
      { date: day(2025, 3), net_worth_cents: 170_000_000 },
      { date: day(2026, 3), net_worth_cents: 190_000_000 },
    ];
    stubFetch({ '/api/summary/history': { points: [...zeros, ...real] } });
    wrap(<NetWorthChart />);
    const chart = await screen.findByRole('img');   // one drawing, at the size useWide picks
    expect(chart.getAttribute('aria-label')).toMatch(/ in March 2024 to .* in March 2026\.$/);
    expect(chart.querySelectorAll('text')[3]).toHaveTextContent('March 2024');
    expect(chart).not.toHaveTextContent('January 2022');
  });

  it('says there is not enough history when only zeros and one balance remain', async () => {
    stubFetch({ '/api/summary/history': { points: [{ date: day(2025, 1), net_worth_cents: 0 }, { date: day(2026, 1), net_worth_cents: 5_000_000 }] } });
    wrap(<NetWorthChart />);
    expect(await screen.findByText('Not enough history yet.')).toBeInTheDocument();
  });

  it('shades the investable part under the line (investment views spec)', async () => {
    stubFetch({ '/api/summary/history': { points: [
      { date: day(2025, 3), net_worth_cents: 150_000_000, investable_cents: 60_000_000 },
      { date: day(2026, 3), net_worth_cents: 190_000_000, investable_cents: 80_000_000 }] } });
    wrap(<NetWorthChart />);
    const chart = await screen.findByRole('img');
    expect(chart.querySelector('polygon.nw-band')).not.toBeNull();
    expect(screen.getByText('The shaded part is investable.')).toBeInTheDocument();
  });

  it('draws no band for history without the investable part', async () => {
    stubFetch({ '/api/summary/history': { points: [{ date: day(2025, 3), net_worth_cents: 150_000_000 }, { date: day(2026, 3), net_worth_cents: 190_000_000 }] } });
    wrap(<NetWorthChart />);
    const chart = await screen.findByRole('img');
    expect(chart.querySelector('polygon.nw-band')).toBeNull();
    expect(screen.queryByText('The shaded part is investable.')).toBeNull();
  });

  it.each([[false, 360, 'nw-wide'], [true, 420, 'nw-wide']])('draws once, at the size useWide picks (wide %s)', async (wide, w, cls) => {
    media(wide);
    stubFetch({ '/api/summary/history': { points: [{ date: day(2025, 3), net_worth_cents: 150_000_000 }, { date: day(2026, 3), net_worth_cents: 190_000_000 }] } });
    wrap(<NetWorthChart />);
    const chart = await screen.findByRole('img');
    expect(screen.getAllByRole('img')).toHaveLength(1);
    expect(chart.getAttribute('viewBox')).toBe(`-44 -10 ${w + 44} ${wide ? 190 : 160}`);
    expect(chart.classList.contains(cls)).toBe(wide);
  });

  it('draws the last 90 days small, beside the years (the sparkline moved here from Home)', async () => {
    const isoDay = (i: number) => {
      const d = new Date(2026, 6, 2 + i);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    };
    stubFetch({ '/api/summary/history': { points: Array.from({ length: 120 }, (_, i) => ({ date: isoDay(i), net_worth_cents: 150_000_000 + i * 10_000 })) } });
    wrap(<NetWorthChart />);
    const recent = await screen.findByRole('img', { name: /^Last 90 days: from / });
    expect(recent.getAttribute('aria-label')).toBe('Last 90 days: from $1,503,000.00 to $1,511,900.00');
    expect(screen.getByText('Last 90 days', { selector: 'p' })).toBeInTheDocument();
  });
});
