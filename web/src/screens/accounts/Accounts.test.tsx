import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useFakeTimers } from '../../test-clock';
import type { BookSummary } from '../../api/types';
import { HouseholdOnly } from '../../book/BookScope';
import { LIMITS_UNAVAILABLE, NET_WORTH_SPLIT_UNAVAILABLE } from '../../lib/copy';
import { BOOK, callsTo, renderAt, stubFetch, wrapBook } from '../../test-utils';
import Settings from '../Settings';
import Accounts, { freshLine, loadLimits, loadNetWorth, loadSplit } from './Accounts';
import { ACCTS, acct } from './fixtures';
import { LINE } from './invest/fixtures';

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); vi.restoreAllMocks(); });

const ours: BookSummary = BOOK;
const mom: BookSummary = { ...BOOK, slug: 'mom', name: 'Mom', kind: 'parent' };
const viewerOf = (b: BookSummary): BookSummary => ({ ...b, role: 'viewer' });
// Local times, so the lines read the same in any time zone.
const at = (d: number, h: number, m: number) => new Date(2026, 9, d, h, m);

describe('freshLine', () => {
  const now = at(25, 18, 0);
  it('says today with the time of the last update', () => {
    expect(freshLine(ACCTS, at(25, 6, 10).toISOString(), now)).toBe('4 accounts · updated today, 6:10 AM');
  });
  it('says yesterday', () => {
    expect(freshLine(ACCTS, at(24, 18, 45).toISOString(), now)).toBe('4 accounts · updated yesterday, 6:45 PM');
  });
  it('gives the date when it is older', () => {
    expect(freshLine(ACCTS, at(23, 6, 10).toISOString(), now)).toBe('4 accounts · updated Oct 23');
  });
  it('says 1 account for one', () => {
    expect(freshLine([ACCTS[0]], at(25, 6, 10).toISOString(), now)).toBe('1 account · updated today, 6:10 AM');
  });
  it('says 12:05 AM just after midnight and 12:05 PM just after noon', () => {
    expect(freshLine(ACCTS, at(25, 0, 5).toISOString(), now)).toBe('4 accounts · updated today, 12:05 AM');
    expect(freshLine(ACCTS, at(25, 12, 5).toISOString(), now)).toBe('4 accounts · updated today, 12:05 PM');
  });
  it('gives the year for a sync in an earlier year', () => {
    expect(freshLine(ACCTS, new Date(2025, 11, 30, 6, 10).toISOString(), now)).toBe('4 accounts · updated Dec 30, 2025');
  });
  it('only counts when SimpleFIN has never updated', () => {
    expect(freshLine(ACCTS, null, now)).toBe('4 accounts');
    expect(freshLine([ACCTS[0]], null, now)).toBe('1 account');
  });
});

describe('the Accounts tab', () => {
  it('says how fresh it is, then All transactions, then the groups (decision 6)', async () => {
    useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(at(25, 18, 0));
    stubFetch({ '/api/accounts': { accounts: ACCTS }, '/api/simplefin': { linked: true, last_sync_at: at(25, 6, 10).toISOString(), last_error: null } });
    wrapBook(<Accounts />, ours, '/b/ours/accounts');
    expect(await screen.findByText('4 accounts · updated today, 6:10 AM')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Accounts' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'All transactions' })).toHaveAttribute('href', '/b/ours/transactions');
    expect(within(document.querySelector('.acct-groups') as HTMLElement).getAllByRole('heading', { level: 2 }).map((h) => h.textContent))
      .toEqual(['Cash', 'Credit', 'Investments', 'Updated manually']);
    expect(screen.getByRole('link', { name: /Checking ••6789/ })).toHaveAttribute('href', '/b/ours/accounts/1');
    expect(screen.getByRole('link', { name: /Roth IRA/ })).toHaveTextContent('Robo Invest');
    // A manual account says when the person last updated it, not the group's name again (the mockup's line).
    expect(screen.getByRole('link', { name: /House/ })).toHaveTextContent('Last updated Today');
    expect(screen.getByRole('link', { name: /House/ })).not.toHaveTextContent('Updated manually');
    // Balances are plain, as on Home: a positive one is not tinted as money coming in.
    expect(within(screen.getByRole('link', { name: /Checking ••6789/ })).getByText('$4,210.18')).not.toHaveClass('money--in');
  });

  it('a group shows its total, and an account with no balance says so', async () => {
    const accounts = [...ACCTS, acct({ id: 5, name: 'Savings ••1123', type: 'savings', balance_cents: 100000 }), acct({ id: 6, name: 'Car', type: 'mortgage', source: 'manual', balance_cents: null, as_of: null })];
    stubFetch({ '/api/accounts': { accounts }, '/api/simplefin': { linked: true, last_sync_at: null, last_error: null } });
    wrapBook(<Accounts />, ours, '/b/ours/accounts');
    const cash = (await screen.findByRole('heading', { level: 2, name: 'Cash' })).closest('section')!;
    expect(within(cash).getAllByText('$5,210.18')).toHaveLength(1);
    expect(within(cash).getByText('$5,210.18')).not.toHaveClass('money--in');
    expect(screen.getByRole('link', { name: /^Car/ })).toHaveTextContent('No balance yet');
    // Updated manually has no total: it would net a house against a car loan.
    const manual = screen.getByRole('heading', { level: 2, name: 'Updated manually' }).parentElement!;
    expect(within(manual).queryByText(/\$/)).toBeNull();
  });

  it('Add an account offers Link a bank, One you update manually and Import files', async () => {
    stubFetch({ '/api/accounts': { accounts: ACCTS }, '/api/simplefin': { linked: true, last_sync_at: null, last_error: null } });
    wrapBook(<Accounts />, ours, '/b/ours/accounts');
    fireEvent.click(await screen.findByRole('button', { name: 'Add an account' }));
    const sheet = screen.getByRole('dialog', { name: 'Add an account' });
    expect(within(sheet).getByRole('link', { name: /Link a bank/ })).toHaveAttribute('href', '/b/ours/settings/banks');
    expect(within(sheet).getByRole('link', { name: /Import files/ })).toHaveAttribute('href', '/b/ours/settings/import');
    fireEvent.click(within(sheet).getByRole('button', { name: /One you update manually/ }));
    expect(await screen.findByLabelText('Name')).toBeInTheDocument();       // the add form
    expect(screen.queryByRole('dialog', { name: 'Add an account' })).toBeNull();
  });

  it('One you update manually keeps focus in the sheet, and closing it goes back to Add an account', async () => {
    // jsdom doesn't know inert; a browser won't focus anything under it, so neither does this test.
    const focus = HTMLElement.prototype.focus;
    vi.spyOn(HTMLElement.prototype, 'focus').mockImplementation(function (this: HTMLElement, opts?: FocusOptions) {
      if (!this.closest('[inert]')) focus.call(this, opts);
    });
    stubFetch({ '/api/accounts': { accounts: ACCTS }, '/api/simplefin': { linked: true, last_sync_at: null, last_error: null } });
    wrapBook(<Accounts />, ours, '/b/ours/accounts');
    const add = await screen.findByRole('button', { name: 'Add an account' });
    add.focus();
    fireEvent.click(add);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /One you update manually/ }));
    const form = screen.getByRole('dialog');
    expect(within(form).getByLabelText('Name')).toBeInTheDocument();
    expect(form).toContainElement(document.activeElement as HTMLElement);
    fireEvent.click(within(form).getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByRole('button', { name: 'Add an account' })).toHaveFocus();
  });

  it('a viewer gets no Add an account', async () => {
    stubFetch({ '/api/accounts': { accounts: ACCTS }, '/api/simplefin': { linked: true, last_sync_at: null, last_error: null } });
    wrapBook(<Accounts />, viewerOf(ours), '/b/ours/accounts');
    await screen.findByRole('link', { name: 'All transactions' });
    expect(screen.queryByRole('button', { name: 'Add an account' })).toBeNull();
  });

  // The book's routes as routes.tsx has them, so the redirects can be followed.
  const routes = (
    <Routes>
      <Route path="/b/:slug/accounts" element={<HouseholdOnly to="/inventory"><Accounts /></HouseholdOnly>} />
      <Route path="/b/:slug/settings/:section?/:step?" element={<Settings />} />
      <Route path="*" element={null} />
    </Routes>
  );
  it.each(['/accounts', '/settings/accounts'])('a parent book has no Accounts tab: %s goes to Inventory', async (path) => {
    stubFetch({});
    const { location } = renderAt(routes, mom, path, [mom]);
    await waitFor(() => expect(location.current.pathname).toBe('/b/mom/inventory'));
  });

  it("shows the plan's tax mix and net worth over time below the cards, before Add an account (plan subpages decision 6)", async () => {
    stubFetch({
      '/api/accounts': { accounts: ACCTS }, '/api/simplefin': { linked: true, last_sync_at: null, last_error: null },
      '/api/summary/history': { points: [{ date: '2025-03-15', net_worth_cents: 150_000_000 }, { date: '2026-03-15', net_worth_cents: 190_000_000 }] },
    });
    wrapBook(<Accounts />, ours, '/b/ours/accounts');
    const tax = await screen.findByRole('heading', { level: 2, name: "Your money, by how it's taxed" });
    const nw = await screen.findByRole('heading', { level: 2, name: 'Net worth over time' });
    const add = screen.getByRole('button', { name: 'Add an account' });
    const groups = document.querySelector('.acct-groups')!;
    const before = (a: Node, b: Node) => expect(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    before(groups, tax);
    before(tax, nw);
    before(nw, add);
    expect(screen.getByText('Counted in the plan')).toBeInTheDocument();
    await waitFor(() => expect(document.querySelectorAll('svg.nw-chart')).toHaveLength(1));   // one drawing, at the size useWide picks
  });

  it('when accounts fail, no tax mix, so never a $0 counted total', async () => {
    stubFetch({
      '/api/accounts': () => new Response(JSON.stringify({ error: 'Accounts are unavailable.' }), { status: 500, headers: { 'content-type': 'application/json' } }),
      '/api/simplefin': { linked: false, last_sync_at: null, last_error: null },
    });
    wrapBook(<Accounts />, ours, '/b/ours/accounts');
    expect(await screen.findByText('Accounts are unavailable.')).toBeInTheDocument();
    expect(screen.queryByText('Counted in the plan')).toBeNull();
  });

  it("still shows the screen when the net worth chunk can't be fetched, and says so", async () => {
    const { default: Missing } = await loadNetWorth(() => Promise.reject(new Error('Failed to fetch dynamically imported module')));
    wrapBook(<Missing />);
    expect(screen.getByRole('heading', { level: 2, name: 'Net worth over time' })).toBeInTheDocument();
    expect(screen.getByText("Net worth over time couldn't load. Reload the page to try again.")).toBeInTheDocument();
  });
  it('shows the contribution limits once, after net worth over time, when there are retirement accounts', async () => {
    stubFetch({
      '/api/accounts': { accounts: ACCTS }, '/api/simplefin': { linked: true, last_sync_at: null, last_error: null },
      '/api/summary/history': { points: [] }, '/api/contributions': { year: 2026, missing: false, lines: [LINE] },
    });
    wrapBook(<Accounts />, ours, '/b/ours/accounts');
    const limits = await screen.findByRole('region', { name: 'Contribution limits for 2026' });
    const nw = await screen.findByRole('heading', { level: 2, name: 'Net worth over time' });
    expect(nw.compareDocumentPosition(limits) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(limits).getByText(/^On pace for \$21,800 by Dec 31/)).toBeInTheDocument();
  });

  it('asks for no limits when there is no retirement account', async () => {
    const fetchMock = stubFetch({ '/api/accounts': { accounts: ACCTS.filter((a) => a.type !== 'roth_ira') }, '/api/simplefin': { linked: false, last_sync_at: null, last_error: null } });
    wrapBook(<Accounts />, ours, '/b/ours/accounts');
    await screen.findByRole('heading', { level: 2, name: 'Net worth over time' });
    expect(callsTo(fetchMock, 'GET', '/api/contributions')).toHaveLength(0);
  });

  it("still shows the screen when the limits chunk can't be fetched, and says so", async () => {
    const { default: Missing } = await loadLimits(() => Promise.reject(new Error('Failed to fetch dynamically imported module')));
    wrapBook(<Missing />);
    expect(screen.getByText(LIMITS_UNAVAILABLE)).toBeInTheDocument();
  });

  it('opens with net worth split into its lines, above All transactions', async () => {
    stubFetch({
      '/api/accounts': { accounts: ACCTS }, '/api/simplefin': { linked: true, last_sync_at: null, last_error: null },
      '/api/summary': { net_worth_cents: 100, month_start: '2026-10-01', change_month_cents: null, year_start: '2026-01-01', change_year_cents: null,
        as_of: '2026-10-25', accounts_by_type: {}, needs_attention: [], split: {
          investable: { cents: 100, account_ids: [1] }, home_and_cars: { cents: 0, account_ids: [] }, owed: { cents: 0, account_ids: [] },
          business: { cents: 0, account_ids: [] }, unset: { cents: 0, account_ids: [] } } },
    });
    wrapBook(<Accounts />, ours, '/b/ours/accounts');
    const split = await screen.findByRole('region', { name: 'Net worth' });
    const all = screen.getByRole('link', { name: 'All transactions' });
    expect(split.compareDocumentPosition(all) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("a vehicle's row names its loan", async () => {
    const subaru = acct({ id: 9, name: 'Subaru', type: 'vehicle', source: 'manual', balance_cents: 2000000, institution: 'Manual', loan_id: 10 });
    const loan = acct({ id: 10, name: 'Car loan', type: 'loan', source: 'manual', balance_cents: -980000, institution: 'Manual' });
    stubFetch({ '/api/accounts': { accounts: [...ACCTS, subaru, loan] }, '/api/simplefin': { linked: false, last_sync_at: null, last_error: null } });
    wrapBook(<Accounts />, ours, '/b/ours/accounts');
    expect(within(await screen.findByRole('link', { name: /^Subaru/ })).getByText('car loan $9,800')).toBeInTheDocument();
  });

  it("still shows the screen when the split's chunk can't be fetched, and says so", async () => {
    const { default: Missing } = await loadSplit(() => Promise.reject(new Error('Failed to fetch dynamically imported module')));
    wrapBook(<Missing />);
    expect(screen.getByText(NET_WORTH_SPLIT_UNAVAILABLE)).toBeInTheDocument();
  });
});
