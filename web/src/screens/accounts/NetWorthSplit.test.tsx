import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Summary } from '../../api/types';
import { ME, stubFetch, wrapBook } from '../../test-utils';
import { ACCTS, acct } from './fixtures';
import { forgetJoy, MILESTONE_KEY } from './joy';
import NetWorthSplit from './NetWorthSplit';

const fx = vi.hoisted(() => ({ burst: vi.fn() }));
vi.mock('../../celebrate/celebrate', () => ({ burst: fx.burst, acorn: vi.fn(() => () => {}), winMoment: vi.fn(() => () => {}) }));
beforeEach(() => { localStorage.clear(); forgetJoy(); fx.burst.mockClear(); });

afterEach(() => vi.unstubAllGlobals());

const subaru = acct({ id: 9, name: 'Subaru', type: 'vehicle', source: 'manual', balance_cents: 2000000, institution: 'Manual', loan_id: 10 });
const carLoan = acct({ id: 10, name: 'Car loan', type: 'loan', source: 'manual', balance_cents: -980000, institution: 'Manual' });
const SUMMARY: Summary = {
  net_worth_cents: 37420000, month_start: '2026-10-01', change_month_cents: null, year_start: '2026-01-01', change_year_cents: 200000,
  as_of: '2026-10-25', accounts_by_type: {}, needs_attention: [],
  split: {
    investable: { cents: 16500000, account_ids: [1, 3] }, home_and_cars: { cents: 52000000, account_ids: [4, 9] },
    owed: { cents: -31080000, account_ids: [2, 10] }, business: { cents: 0, account_ids: [] }, unset: { cents: 0, account_ids: [] },
  },
};
const show = (summary: Summary = SUMMARY) => {
  stubFetch({ '/api/auth/me': ME, '/api/summary': summary, '/api/accounts': { accounts: [...ACCTS, subaru, carLoan] } });
  wrapBook(<NetWorthSplit />);
};

describe('net worth at the top of Accounts (investment views spec, Net worth)', () => {
  it('shows net worth, its change this year, and three lines that add up to it', async () => {
    show();
    const sec = await screen.findByRole('region', { name: 'Net worth' });
    expect(within(sec).getByTestId('nws-total')).toHaveTextContent('$374,200.00');
    expect(within(sec).getByText('Up $2,000 this year')).toBeInTheDocument();
    expect(within(sec).getAllByText(/^(Investable|Home and cars|What you owe|Business|Type not set yet)$/).map((e) => e.textContent))
      .toEqual(['Investable', 'Home and cars', 'What you owe']);
    expect(within(sec).getAllByTestId('nws-line').map((e) => e.textContent)).toEqual(['$165,000.00', '$520,000.00', '−$310,800.00']);
  });

  it('opens a line to its accounts, a vehicle with its loan', async () => {
    show();
    const sec = await screen.findByRole('region', { name: 'Net worth' });
    fireEvent.click(within(sec).getByText('Home and cars'));
    expect(within(sec).getByRole('link', { name: 'Subaru · car loan $9,800' })).toHaveAttribute('href', '/b/ours/accounts/9');
    expect(within(sec).getByRole('link', { name: 'House' })).toHaveAttribute('href', '/b/ours/accounts/4');
  });

  it('adds Business and Type not set yet only when they have accounts, and says Down when it fell', async () => {
    show({ ...SUMMARY, change_year_cents: -500000, split: { ...SUMMARY.split,
      business: { cents: 250000, account_ids: [11] }, unset: { cents: 42100, account_ids: [12] } } });
    const sec = await screen.findByRole('region', { name: 'Net worth' });
    expect(within(sec).getByText('Down $5,000 this year')).toBeInTheDocument();
    expect(within(sec).getByText('Business')).toBeInTheDocument();
    expect(within(sec).getByText('Type not set yet')).toBeInTheDocument();
  });

  it('says nothing of this year without a balance from last year', async () => {
    show({ ...SUMMARY, change_year_cents: null });
    await screen.findByRole('region', { name: 'Net worth' });
    expect(screen.queryByText(/this year$/)).toBeNull();
  });

  it('crossing a milestone cheers once on this device; the first look only records where it stands', async () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: false, media: q, addEventListener: () => {}, removeEventListener: () => {} }));
    show({ ...SUMMARY, net_worth_cents: 95_000_000 });
    await screen.findByRole('region', { name: 'Net worth' });
    expect(screen.queryByText(/just crossed/)).toBeNull();
    expect(localStorage.getItem(`${MILESTONE_KEY}:1:ours`)).toBe('90000000');
  });

  it('a higher milestone says "Net worth just crossed $1,000,000. Look at that." with a burst', async () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: false, media: q, addEventListener: () => {}, removeEventListener: () => {} }));
    localStorage.setItem(`${MILESTONE_KEY}:1:ours`, '90000000');
    show({ ...SUMMARY, net_worth_cents: 100_500_000 });
    expect(await screen.findByText('Net worth just crossed $1,000,000. Look at that.')).toBeInTheDocument();
    await waitFor(() => expect(fx.burst).toHaveBeenCalledTimes(1));
  });
});
