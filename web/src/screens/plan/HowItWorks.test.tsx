import { fireEvent, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { reply, stubFetch, wrapBook } from '../../test-utils';
import { CHILDREN, FACTS, planFixture } from './fixtures';
import { HowItWorks } from './HowItWorks';

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); });

const routes = (extra: Record<string, unknown> = {}) => stubFetch({
  '/api/facts': FACTS, '/api/children': CHILDREN, '/api/accounts': { accounts: [] }, '/api/ss': { records: { jr: null, spouse: null } }, ...extra,
});

describe('How it works (plan subpages decision 5)', () => {
  it('leads with what moves the plan most, lists notices unfolded in amber, and folds the rest', async () => {
    routes();
    wrapBook(<HowItWorks data={planFixture()} />, {}, '/b/ours/plan/how');
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent))
      .toEqual(['What moves your plan most', 'Where your numbers come from', 'What the ages mean']);
    const moves = screen.getByRole('region', { name: 'What moves your plan most' });
    expect([...moves.querySelectorAll('.facts__row')].map((r) => r.textContent)).toEqual([
      'Social Security at 67JR $3,354 · Sam $1,677 a month Change', 'Spending in retirement$7,400 a month Change',
      'Mortgage paid off2050 Change', 'Health before Medicare$16,800 a year Change', 'College3 kids · in-state Change',
      'Saving now$2,150 a month']);
    expect(within(moves).getByRole('link', { name: 'Change Social Security at 67' })).toHaveAttribute('href', '/b/ours/profile/benefits?from=plan');
    expect(within(moves).getByRole('link', { name: 'Change Spending in retirement' })).toHaveAttribute('href', '/b/ours/plan/try');
    expect(within(moves).getByRole('link', { name: 'Change Mortgage paid off' })).toHaveAttribute('href', '/b/ours/profile/home?from=plan');
    expect(within(moves).getByRole('link', { name: 'Change College' })).toHaveAttribute('href', '/b/ours/profile/kids?from=plan');
    const notices = document.querySelectorAll('.how-notices li.warn');
    expect([...notices].map((n) => n.textContent)).toEqual([
      'Acme Stable Value Fund has no holdings listed, so it uses the default mix for its type.', 'Based on 7 months of spending history, annualized.']);
    const folds = screen.getAllByRole('group');
    expect(folds.map((f) => f.querySelector('summary')!.textContent)).toEqual(['Markets', 'Social Security rules']);
    expect(folds.every((f) => !(f as HTMLDetailsElement).open)).toBe(true);
    expect(within(folds[0]).getByText('Steward runs your money through 2,000 simulated market histories built from real market returns since 1928.')).toBeInTheDocument();
    expect(within(folds[1]).getByText('Social Security benefits are cut 17% from 2034 (2026 Trustees Report).')).toBeInTheDocument();
    expect(await screen.findByText('Comfortably is the first age at which the money lasts until Sam is 95 in 9 of 10 histories. Likely is the first age at which it lasts in 8 of 10.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Pay' })).toHaveAttribute('href', '/b/ours/profile/you?from=plan');
  });

  it('a viewer sees the numbers with no Change links', () => {
    routes();
    wrapBook(<HowItWorks data={planFixture()} />, { role: 'viewer' }, '/b/ours/plan/how');
    expect(within(screen.getByRole('region', { name: 'What moves your plan most' })).queryByRole('link')).toBeNull();
  });

  it('a fold opened stays open for this viewer, and a blocked store leaves them closed', () => {
    routes();
    const { unmount } = wrapBook(<HowItWorks data={planFixture()} />, {}, '/b/ours/plan/how');
    const markets = screen.getAllByRole('group')[0] as HTMLDetailsElement;
    markets.open = true;
    fireEvent(markets, new Event('toggle'));
    unmount();
    const second = wrapBook(<HowItWorks data={planFixture()} />, {}, '/b/ours/plan/how');
    expect((screen.getAllByRole('group')[0] as HTMLDetailsElement).open).toBe(true);
    second.unmount();
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    wrapBook(<HowItWorks data={planFixture()} />, {}, '/b/ours/plan/how');
    expect((screen.getAllByRole('group')[0] as HTMLDetailsElement).open).toBe(false);
  });

  it('keeps its rows while accounts fail, saying balances are not available', async () => {
    routes({ '/api/accounts': () => reply({ error: 'Accounts are unavailable.' }, 500) });
    wrapBook(<HowItWorks data={planFixture()} />, {}, '/b/ours/plan/how');
    expect(await screen.findByText('not available')).toBeInTheDocument();
  });

  it('says loading while accounts are on their way', () => {
    routes({ '/api/accounts': () => new Promise(() => {}) });
    wrapBook(<HowItWorks data={planFixture()} />, {}, '/b/ours/plan/how');
    expect(screen.getByText('loading')).toBeInTheDocument();
  });
});
