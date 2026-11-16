import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { reply, stubFetch, wrapBook } from '../../../test-utils';
import { acct } from '../fixtures';
import { forgetJoy } from '../joy';
import { LINE, page } from './fixtures';
import Investment from './Investment';

const fx = vi.hoisted(() => ({ loaded: vi.fn(), burst: vi.fn() }));
vi.mock('../../../celebrate/celebrate', () => { fx.loaded(); return { burst: fx.burst, acorn: vi.fn(() => () => {}), winMoment: vi.fn(() => () => {}) }; });

beforeEach(() => { localStorage.clear(); forgetJoy(); });
afterEach(() => { vi.unstubAllGlobals(); fx.burst.mockClear(); fx.loaded.mockClear(); });

const motion = (reduce: boolean) => vi.stubGlobal('matchMedia', (q: string) => ({
  matches: reduce && q.includes('reduce'), media: q, addEventListener: () => {}, removeEventListener: () => {} }));
const k401 = acct({ id: 3, name: '401(k)', type: 'k401', owner: 'jr', institution: 'Workplace' });
const MAXED = page({ type: 'k401', contributions: {
  this_year: { you_cents: 2450000, you_from: 'deposits', match_cents: 0, match_from: 'none', rollover_cents: 0, out_cents: 0 },
  missing: false, line: { ...LINE, in_cents: 2450000, maxed: true, short_cents: 0, raise_pct: null } } });

describe("the page's cheers (investment views spec, Joy)", () => {
  it('a limit reached cheers once on this device, with a burst while celebrations are on', async () => {
    motion(false);
    stubFetch({ '/api/accounts/3/investment': MAXED });
    const { unmount } = wrapBook(<Investment account={k401} />);
    expect(await screen.findByText('Maxed your 401(k) for 2026.')).toBeInTheDocument();
    await waitFor(() => expect(fx.burst).toHaveBeenCalledTimes(1));
    unmount();
    wrapBook(<Investment account={k401} />);
    await screen.findByText(/Maxed for 2026\./);
    expect(screen.queryByText('Maxed your 401(k) for 2026.')).toBeNull();
    expect(fx.burst).toHaveBeenCalledTimes(1);
  });

  it('on a device set to reduce motion the cheer is still said, and nothing loads or moves', async () => {
    motion(true);
    stubFetch({ '/api/accounts/3/investment': MAXED });
    wrapBook(<Investment account={k401} />);
    expect(await screen.findByText('Maxed your 401(k) for 2026.')).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 0));
    expect(fx.loaded).not.toHaveBeenCalled();
    expect(fx.burst).not.toHaveBeenCalled();
  });

  it("the first import into an account says so: Now you can see what it's made of.", async () => {
    motion(false);
    const ready = { needs_mapping: false, remembered: true, headers: ['Symbol', 'Market Value'],
      mapping: { symbol: 'Symbol', name: null, shares: null, value: 'Market Value', cost_basis: null }, as_of: '2026-10-28',
      count: 1, total_cents: 100, balance_cents: null, difference_cents: null, positions: [{ symbol: 'VTI', name: 'VTI', value_cents: 100 }] };
    stubFetch({
      '/api/accounts/3/investment': page({ holdings: null, all_in: null }),
      'POST /api/accounts/3/positions/preview': ready,
      'POST /api/accounts/3/positions': () => reply({ count: 1, total_cents: 100, as_of: '2026-10-28', first: true }, 201),
    });
    wrapBook(<Investment account={acct({ id: 3, name: 'Taxable', type: 'brokerage_taxable', institution: 'Robo Invest' })} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Import positions' }));
    fireEvent.change(await screen.findByLabelText('Positions file (CSV)'), { target: { files: [new File(['x'], 'p.csv')] } });
    fireEvent.click(await screen.findByRole('button', { name: 'Save' }));
    expect(await screen.findByText("Now you can see what it's made of.")).toBeInTheDocument();
    await waitFor(() => expect(fx.burst).toHaveBeenCalledTimes(1));
  });
});
