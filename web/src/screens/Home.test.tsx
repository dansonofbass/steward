import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, reply, stubFetch, wrapBook } from '../test-utils';
import { Home } from './Home';
import { ACCOUNTS, HOME, homeWith } from './home/fixtures';

afterEach(() => vi.unstubAllGlobals());
const NO_CONTENT = () => new Response(null, { status: 204 });
const ROUTES = { '/api/home': HOME, '/api/accounts': ACCOUNTS, 'POST /api/home/seen': NO_CONTENT };
const acct = (id: number, name: string, type: string, source: string, extra: Record<string, unknown> = {}) =>
  ({ id, name, type, owner: 'joint', source, institution: 'Bank', is_active: true, balance_cents: 1000, as_of: '2026-10-29', stale_days: 1, ...extra });

async function ready() {
  const v = await screen.findByTestId('verdict');
  await waitFor(() => expect(v).toHaveAttribute('data-ready', 'true'));
  return v;
}

describe('Home (phase 11 spec)', () => {
  it('names the sorted past month beside current Review work (issue #33)', async () => {
    stubFetch({ ...ROUTES,
      '/api/growth': { stage: 1, seen: false, milestones: [
        { key: 'first_month', met: true, month: '2026-09' }, { key: 'covered', met: false },
        { key: 'checklist', met: false }, { key: 'year', met: false }, { key: 'five_years', met: false },
      ] },
      'POST /api/growth/seen': NO_CONTENT,
      '/api/review': { uncategorized: [], count: 1, duplicates: [], duplicate_count: 0, top_categories: [],
        business: [], business_count: 0, background: { pending: 0, done: 0, waiting: false } },
    });
    wrapBook(<Home />);
    expect(await screen.findByText('1 to sort in Review')).toBeInTheDocument();
    expect(await screen.findByText('New growth: September 2026 is fully sorted.')).toBeInTheDocument();
  });

  it('marks home-ready once, only after /api/home and /api/accounts both answer', async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => { release = r; });
    stubFetch({ ...ROUTES, '/api/accounts': async () => { await gate; return reply(ACCOUNTS); } });
    const mark = vi.spyOn(performance, 'mark');
    wrapBook(<Home />);
    const v = await screen.findByTestId('verdict');
    expect(v).not.toHaveAttribute('data-ready');
    expect(mark.mock.calls.filter(([n]) => n === 'home-ready')).toHaveLength(0);
    release();
    await waitFor(() => expect(v).toHaveAttribute('data-ready', 'true'));
    expect(mark.mock.calls.filter(([n]) => n === 'home-ready')).toHaveLength(1);
    mark.mockRestore();
  });

  it('asks /api/home and /api/accounts, and never the endpoints the old Home used', async () => {
    const fetchMock = stubFetch(ROUTES);
    wrapBook(<Home />);
    await ready();
    await screen.findByTestId('flow-strip');
    for (const old of ['/api/summary', '/api/spending', '/api/plan', '/api/same-accounts']) {
      expect(callsTo(fetchMock, 'GET', old)).toEqual([]);
    }
  });

  it("the headline is the page's h1, under the server's day", async () => {
    stubFetch({ ...ROUTES, '/api/home': homeWith({ as_of: '2026-10-27' }) });
    wrapBook(<Home />);
    await ready();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/^A steady month\./);
    expect(screen.getByText('Tuesday, Oct 27')).toBeInTheDocument();
  });

  it('a failed /api/home shows the error and Try again asks again', async () => {
    let fail = true;
    stubFetch({ ...ROUTES, '/api/home': () => (fail ? reply({ error: 'The vault is locked.' }, 503) : reply(HOME)) });
    wrapBook(<Home />);
    expect(await screen.findByText('The vault is locked.')).toBeInTheDocument();
    fail = false;
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await ready();
  });

  it('an empty book says "Nothing to go on yet." with no figure or signs, and the accounts\' empty state', async () => {
    stubFetch({ ...ROUTES, '/api/home': homeWith({ verdict: { ...HOME.verdict, opener: 'empty', clauses: [] } }), '/api/accounts': { accounts: [] } });
    wrapBook(<Home />);
    await ready();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Nothing to go on yet.');
    expect(screen.queryByTestId('figure')).toBeNull();
    expect(screen.queryByTestId('signs')).toBeNull();
    expect(screen.getByText('Nothing here yet.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to Accounts' })).toHaveAttribute('href', '/b/ours/accounts');
  });

  it('a stale account says how old it is, in the warn tone', async () => {
    stubFetch({ ...ROUTES, '/api/accounts': { accounts: [acct(1, 'Checking', 'checking', 'simplefin', { as_of: '2026-10-18', stale_days: 12 })] } });
    wrapBook(<Home />);
    expect(await screen.findByText('12 days old')).toHaveClass('stale');
  });

  it('keeps the day-to-day accounts, each opening its own page, with a link to all accounts', async () => {
    stubFetch({ ...ROUTES, '/api/accounts': { accounts: [acct(1, 'Joint checking', 'checking', 'simplefin'), acct(2, 'Visa', 'credit', 'simplefin'), acct(3, 'Roth', 'roth_ira', 'simplefin'), acct(4, 'House', 'property', 'manual')] } });
    wrapBook(<Home />);
    expect(await screen.findByText('Joint checking')).toBeInTheDocument();
    expect(screen.getAllByTestId('account-row').map((r) => r.textContent)).toEqual([expect.stringContaining('Joint checking'), expect.stringContaining('Visa')]);
    expect(screen.queryByText('Roth')).toBeNull();
    expect(screen.getAllByTestId('account-row')[0]).toHaveAttribute('href', '/b/ours/accounts/1');
    expect(screen.getByRole('link', { name: 'All accounts ›' })).toHaveAttribute('href', '/b/ours/accounts');
  });

  it('a checking account from a file or typed in shows too, as the import makes it (INS-20)', async () => {
    stubFetch({ ...ROUTES, '/api/accounts': { accounts: [acct(1, 'chase_checking', 'checking', 'manual')] } });
    wrapBook(<Home />);
    expect(await screen.findByText('chase_checking')).toBeInTheDocument();
    expect(screen.getAllByTestId('account-row')).toHaveLength(1);
    expect(screen.queryByText('Checking, savings and cards show here.')).toBeNull();
  });

  it('with accounts but none of the day-to-day kind, the section says what shows there', async () => {
    stubFetch({ ...ROUTES, '/api/accounts': { accounts: [acct(4, 'House', 'property', 'manual')] } });
    wrapBook(<Home />);
    expect(await screen.findByText('Checking, savings and cards show here.')).toBeInTheDocument();
    expect(screen.queryByTestId('account-row')).toBeNull();
    expect(screen.getByRole('link', { name: 'All accounts ›' })).toHaveAttribute('href', '/b/ours/accounts');
  });

  it('the strip loads after ready, under the signs, and opens Spending on this month', async () => {
    stubFetch(ROUTES);
    wrapBook(<Home />);
    const strip = await screen.findByTestId('flow-strip');
    expect(strip).toHaveAttribute('href', '/b/ours/spending?month=2026-10');
    expect(screen.getByTestId('signs').compareDocumentPosition(strip) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("sends one glance with the server's mark once ready", async () => {
    const fetchMock = stubFetch(ROUTES);
    wrapBook(<Home />);
    await ready();
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/home/seen')).toHaveLength(1));
    expect(callsTo(fetchMock, 'POST', '/api/home/seen')[0].body).toEqual({ mark: HOME.mark, glance: true });
  });

  it('asks /api/business only for a household with a business, after ready', async () => {
    const fetchMock = stubFetch({ ...ROUTES, '/api/home': homeWith({ signs: { ...HOME.signs, has_business: true } }), '/api/business': { type: 'sole_prop', profit_cents: 421_000 } });
    wrapBook(<Home />);
    expect(await screen.findByRole('link', { name: 'Business: $4,210 profit this year' })).toHaveAttribute('href', '/b/ours/business');
    expect(callsTo(fetchMock, 'GET', '/api/business')).toHaveLength(1);
  });

  it('a household with no business never asks for one', async () => {
    const fetchMock = stubFetch(ROUTES);
    wrapBook(<Home />);
    await ready();
    await screen.findByTestId('flow-strip');
    expect(callsTo(fetchMock, 'GET', '/api/business')).toEqual([]);
  });

  it('For you follows the signs and the strip, from /api/home', async () => {
    stubFetch({ ...ROUTES, '/api/home': homeWith({ for_you: [{ kind: 'event', id: 41, event_kind: 'sync', level: 'warn', message: 'Big Bank needs you to sign in again at SimpleFIN' }] }),
      '/api/review': { uncategorized: [], count: 0, duplicates: [], duplicate_count: 0, top_categories: [], business: [], business_count: 0, background: { pending: 0, done: 0, waiting: false } } });
    wrapBook(<Home />);
    const card = await screen.findByTestId('for-you');
    expect(card).toHaveTextContent('Big Bank needs you to sign in again at SimpleFIN');
    expect(screen.getByTestId('signs').compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('Since loads after ready, after For you, when there was a last look', async () => {
    stubFetch({ ...ROUTES, '/api/home': homeWith({ since: { from: '2026-10-27T19:00:00+00:00', from_day: '2026-10-27', over_month: false, lines: [], more: 0, net_worth_cents: null } }) });
    wrapBook(<Home />);
    const since = await screen.findByTestId('since');
    expect(since).toHaveTextContent('Nothing new since Tuesday.');
    expect(screen.getByTestId('for-you').compareDocumentPosition(since) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('a first visit has no Since section', async () => {
    stubFetch(ROUTES);
    wrapBook(<Home />);
    await ready();
    await screen.findByTestId('flow-strip');
    expect(screen.queryByTestId('since')).toBeNull();
  });
});
