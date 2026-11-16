import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useFakeTimers } from '../../../test-clock';
import { callsTo, renderAt, stubFetch } from '../../../test-utils';
import { FIRST, LIST, YOUNG } from './fixtures';
import { SetAsides } from './SetAsides';

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
beforeEach(() => { useFakeTimers(); });
const rows = () => screen.getAllByTestId('sa-row');
type Spy = { mock: { calls: unknown[][] } };
/** Every write refreshes Spending, the list, the Plan, Transactions and Home's summary (engineering choice 15). */
const expectInvalidated = (spy: Spy) => waitFor(() => expect(spy.mock.calls.map((c) => (c[0] as { queryKey: string[] }).queryKey[0]))
  .toEqual(expect.arrayContaining(['spending', 'setasides', 'plan', 'transactions', 'summary'])));

describe('Setting aside, the list', () => {
  it('heads with the monthly amount, lists soonest due first with each state in the list words, and offers the pills', async () => {
    stubFetch({ '/api/setasides': LIST });
    renderAt(<SetAsides />, {}, '/spending/setasides');
    expect(await screen.findByTestId('sa-head')).toBeInTheDocument();      // the loading page has the heading too
    expect(screen.getByRole('heading', { level: 1, name: 'Setting aside' })).toBeInTheDocument();
    expect(screen.getByTestId('sa-head')).toHaveTextContent('$1,544 a month');
    expect(screen.getByTestId('sa-line')).toHaveTextContent(/^7 costs\s*·\s*\$14,592 a year in yearly costs\s*·\s*\$20,200 in big one-offs\s*·\s*2 need a look$/);
    expect(rows().map((r) => r.getAttribute('data-state'))).toEqual(['short', 'no_account', 'no_account', 'behind', 'no_account', 'on_track', 'on_track']);
    expect(rows()[0]).toHaveTextContent('Property tax');
    expect(rows()[0]).toHaveTextContent('$4,210 twice a year · next Nov 1, 2026, in 7 days');
    expect(rows()[0]).toHaveTextContent('$702');
    expect(rows()[0]).toHaveTextContent('Due in 7 days · $110 short · House fund');
    expect(rows()[0]).toHaveAttribute('href', '/b/ours/spending/setasides/1');
    expect(rows()[3]).toHaveTextContent('Behind by $200 · $600 put away, $800 should be by now · Kids fund');
    expect(rows()[5]).toHaveTextContent('$2,200 once · About 2028, 26 months away');
    expect(within(rows()[5]).getByText('Estimate')).toBeInTheDocument();
    expect(rows()[5]).toHaveTextContent('On track · nothing due yet · House fund');
    expect(rows()[1]).toHaveTextContent('No account linked');
    expect(screen.getByRole('link', { name: /Add a set-aside/ })).toHaveAttribute('href', '/b/ours/spending/setasides/new');
    const pills = screen.getByRole('navigation', { name: 'Spending views' });
    expect(within(pills).getByRole('link', { name: 'Setting aside' })).toHaveAttribute('aria-current', 'page');
    expect(within(pills).getByRole('link', { name: 'This month' })).toHaveAttribute('href', '/b/ours/spending');
    expect(screen.getByText('Set aside each month').parentElement).toHaveTextContent('$1,544');
  });

  it('says "balance from Oct 12" only when the server marks the account stale', async () => {
    const stale = { ...LIST.rows[0], account: { ...LIST.rows[0].account!, stale: true, as_of: '2026-10-12' } };
    stubFetch({ '/api/setasides': { ...LIST, rows: [stale, LIST.rows[1]] } });
    renderAt(<SetAsides />, {}, '/spending/setasides');
    await screen.findAllByTestId('sa-row');
    expect(rows()[0]).toHaveTextContent('House fund, balance from Oct 12');
  });

  it('a dismissed suggestion folds to one line with Bring it back', async () => {
    const fetchMock = stubFetch({
      '/api/setasides': { ...LIST, suggestions: [], dismissed: [{ payee_key: 'COSTBOX', payee_name: 'Costbox', category: 'shopping', monthly_cents: 1_100 }] },
      'POST /api/setasides/suggestions/restore': LIST,
    });
    const { qc } = renderAt(<SetAsides />, {}, '/spending/setasides');
    const spy = vi.spyOn(qc, 'invalidateQueries');
    const row = await screen.findByTestId('sa-dismissed');
    expect(row).toHaveTextContent('Costbox');
    expect(row).toHaveTextContent('Not a set-aside · stays in Shopping');
    expect(row).toHaveTextContent('$11');
    fireEvent.click(within(row).getByRole('button', { name: 'Bring it back: Costbox' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/setasides/suggestions/restore')[0].body).toEqual({ payee_key: 'COSTBOX', category: 'shopping' }));
    await expectInvalidated(spy);
  });

  it('no first-visit notice, ever (P26)', async () => {
    stubFetch({ '/api/setasides': FIRST });
    renderAt(<SetAsides />, {}, '/spending/setasides');
    expect(await screen.findByText('Nothing set aside yet.')).toBeInTheDocument();
    expect(screen.queryByTestId('sa-first-visit')).toBeNull();
  });

  it('a young book says how much history it has', async () => {
    stubFetch({ '/api/setasides': YOUNG });
    renderAt(<SetAsides />, {}, '/spending/setasides');
    expect(await screen.findByTestId('sa-history')).toHaveTextContent('Steward has 3 months of history; yearly costs show up after a year. Older history comes from CSV files.');
    expect(screen.queryByTestId('sa-first-visit')).toBeNull();
    expect(screen.getByText('Nothing yearly in your history yet.')).toBeInTheDocument();
  });

  it('a viewer sees the list and the suggestions with nothing to press', async () => {
    stubFetch({ '/api/setasides': LIST });
    renderAt(<SetAsides />, { role: 'viewer' }, '/spending/setasides');
    await screen.findAllByTestId('sa-row');
    expect(screen.queryByRole('link', { name: /Add a set-aside/ })).toBeNull();
    expect(screen.queryByText('Set it aside')).toBeNull();
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
    expect(screen.queryByText('Change first')).toBeNull();
    expect(screen.queryByText('Not this one')).toBeNull();
    expect(screen.getByText('Not counted until a manager sets them aside.')).toBeInTheDocument();
    expect(screen.getAllByTestId('sa-suggestion')).toHaveLength(3);
  });

  it('says when the list could not be loaded', async () => {
    stubFetch({ '/api/setasides': () => new Response(JSON.stringify({ error: 'Nope.' }), { status: 503 }) });
    renderAt(<SetAsides />, {}, '/spending/setasides');
    expect(await screen.findByRole('alert')).toHaveTextContent('Nope.');
  });
});
