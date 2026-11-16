import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Txn } from '../../api/types';
import { askState, resetAsk } from '../../ask/store';
import { callsTo, renderAt, reply, stubFetch } from '../../test-utils';
import { Category } from './Category';
import { OCT, SEP, TRENDS } from './fixtures';

afterEach(() => vi.unstubAllGlobals());

const txn = (id: number, posted_at: string, amount_cents: number, merchant: string, more: Partial<Txn> = {}): Txn => ({
  id, account_id: 3, account_name: 'Rewards Card', posted_at, amount_cents, raw_description: merchant.toUpperCase(), merchant,
  category: 'dining', is_business: false, is_transfer: false, business_pct: 0, business_line: null, business_source: 'none',
  category_source: 'rule', reviewed_at: null, from_bank: true, ...more,
});
const TXNS = { next_cursor: null, transactions: [
  txn(1, '2026-10-24', -4_212, 'Noodle House'),
  txn(2, '2026-10-22', 1_384, 'Noodle House'),
  txn(3, '2026-10-20', -6_000, 'Bean & Leaf', { business_pct: 40 }),
  txn(4, '2026-10-20', -2_500, 'Client lunch', { business_pct: 100, is_business: true }),
  // Ruling 2: a refund of a business row, or of a transfer, is out of Spending, not "counted against" the category.
  txn(5, '2026-10-19', 1_000, 'Client lunch refund', { business_pct: 100, is_business: true }),
  txn(6, '2026-10-18', 3_000, 'Card payment back', { is_transfer: true }),
  txn(7, '2026-10-17', 2_000, 'Phone refund', { business_pct: 40 }),
] };
const NONE = { transactions: [], next_cursor: null };
const ROUTES = { '/api/spending': OCT, '/api/spending/trends': TRENDS, '/api/transactions': TXNS };
const open = (path: string, book = {}) => renderAt(
  <Routes>
    <Route path="/b/:slug/spending/:category" element={<Category />} />
    <Route path="/b/:slug/spending" element={<p>Spending page</p>} />
  </Routes>, book, path);

describe('one category', () => {
  it("a manager changes the category's kind at once, with Undo", async () => {
    const fetchMock = stubFetch({ ...ROUTES, 'PUT /api/spending/kinds/giving': { category: 'giving', kind: 'fixed', undo: 'tok-k' }, 'POST /api/undo/tok-k': { undone: 0, transaction: null } });
    open('/spending/giving?month=2026-10');
    const select = await screen.findByRole('combobox', { name: 'Kind of Giving' });
    expect(select).toHaveValue('commitment');
    expect([...select.querySelectorAll('option')].map((o) => o.textContent)).toEqual(['Bill', 'Commitment', 'Flexible', 'Once in a while']);
    fireEvent.change(select, { target: { value: 'fixed' } });
    expect(await screen.findByRole('status')).toHaveTextContent('Giving is a bill · Undo');
    expect(callsTo(fetchMock, 'PUT', '/api/spending/kinds/giving')[0].body).toEqual({ kind: 'fixed' });
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/undo/tok-k')).toHaveLength(1));
  });
  it('a viewer has no kind select', async () => {
    stubFetch(ROUTES);
    open('/spending/giving?month=2026-10', { role: 'viewer' });
    await screen.findByTestId('cat-total');
    expect(screen.queryByRole('combobox', { name: 'Kind of Giving' })).toBeNull();
  });
  it("shows Eating out's pace, its last months, and this month's transactions with the refund marked", async () => {
    const fetchMock = stubFetch(ROUTES);
    open('/spending/dining?month=2026-10');
    expect(await screen.findByText('Eating out · October 2026')).toBeInTheDocument();
    expect(screen.getByTestId('cat-total')).toHaveTextContent('$468 of $500');
    expect(screen.getByTestId('cat-state')).toHaveTextContent('On track · 6 days left');
    expect(screen.getByText('$13.84 came back in refunds, counted against Eating out.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Change the target' })).toHaveAttribute('href', '/b/ours/spending/targets');
    const tiles = await screen.findAllByTestId('last3-tile');
    expect(tiles.map((t) => t.textContent)).toEqual(['Jul$480of $500', 'Aug$560$60 over', 'Sep$490of $500']);
    expect(within(tiles[1]).getByText('$560')).toHaveClass('is-over');
    expect(screen.getByText('Over the target in 4 of the last 12 months. The typical month is $470.')).toBeInTheDocument();
    // Task 8's chart as it is: aria-hidden bars, the card's text says the target once, October is faded.
    expect(screen.getByText('Target $500 · typical month $470')).toBeInTheDocument();
    const bars = document.querySelectorAll('rect.sp-chart__bar');
    expect(bars).toHaveLength(12);
    expect(bars[11]).toHaveClass('so-far');
    expect(screen.getByText('so far')).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByTestId('cat-txn')).toHaveLength(7));
    expect(callsTo(fetchMock, 'GET', '/api/transactions')[0].url).toContain('category=dining&from=2026-10-01&to=2026-10-25');
    const rows = screen.getAllByTestId('cat-txn');
    expect(rows[0]).toHaveTextContent('Rewards Card');
    expect(rows[1]).toHaveTextContent('counts against Eating out');
    expect(rows[2]).toHaveTextContent('your 60% counts');
    expect(rows[3]).toHaveTextContent('not counted in Spending');
    expect(rows[4]).toHaveTextContent('not counted in Spending');
    expect(rows[4]).not.toHaveTextContent('counts against');
    expect(rows[5]).toHaveTextContent('not counted in Spending');
    expect(rows[5]).not.toHaveTextContent('counts against');
    expect(rows[6]).toHaveTextContent('your 60% counts');
    expect(rows[6]).not.toHaveTextContent('counts against');
    // Ruling 3: the month view's count and the listed rows can differ, so the section head claims neither.
    expect(screen.getByRole('heading', { name: "This month's transactions" }).parentElement).toHaveTextContent(/^This month's transactions$/);
    expect(screen.getByRole('link', { name: 'All Eating out transactions' })).toHaveAttribute('href', '/b/ours/transactions?category=dining');
    expect(screen.getByRole('link', { name: 'Spending' })).toHaveAttribute('href', '/b/ours/spending?month=2026-10');
  });

  it('a fixed cost shows what was expected and when it came out', async () => {
    stubFetch({ ...ROUTES, '/api/transactions': NONE });
    open('/spending/housing?month=2026-10');
    expect(await screen.findByTestId('cat-total')).toHaveTextContent('$2,680');
    expect(screen.getByTestId('cat-state')).toHaveTextContent('Expected $2,680 · Home loan · came out Oct 1');
    expect(document.querySelector('.sp-cat-head .sp-pace__bar')).toBeNull();
  });

  it('a commitment part way through says the usual once, with no Expected before it', async () => {
    const m = { ...OCT, fixed: OCT.fixed.map((r) => (r.category === 'giving'
      ? { ...r, expected_cents: 28_000, usual_cents: 28_000, spent_cents: 18_700, state: 'so_far' as const, came_out_on: null, merchant: null }
      : r)) };
    stubFetch({ ...ROUTES, '/api/spending': m, '/api/transactions': NONE });
    open('/spending/giving?month=2026-10');
    expect(await screen.findByTestId('cat-state')).toHaveTextContent(/^\$187 so far · usually \$280$/);
    expect(screen.getByTestId('cat-state')).not.toHaveTextContent('Expected');
  });

  it('a fixed cost with nothing expected still draws its months, with no line to judge them by (ruling 24)', async () => {
    const m = { ...OCT, fixed: OCT.fixed.map((r) => (r.category === 'childcare_education' ? { ...r, expected_cents: null } : r)) };
    const unjudged = { category: 'childcare_education', kind: 'fixed' as const, group: 'unjudged' as const, target_cents: null,
      expected_cents: null, typical_cents: null, spent: [0, 0, 0, 0, 0, 0, 0, 0, 80_000, 0, 0, 82_000], over_in: 0, over_of: 6, order: 9 };
    stubFetch({ ...ROUTES, '/api/spending': m, '/api/spending/trends': { ...TRENDS, categories: [...TRENDS.categories, unjudged] }, '/api/transactions': NONE });
    open('/spending/childcare_education?month=2026-10');
    expect(await screen.findByTestId('cat-state')).toHaveTextContent(/^Little Sprouts · came out Oct 2$/);
    expect(screen.getByRole('heading', { name: 'Last 12 months' })).toBeInTheDocument();
    expect(document.querySelectorAll('rect.sp-chart__bar')).toHaveLength(12);
    expect(document.querySelector('.sp-chart__target')).toBeNull();
    expect((await screen.findAllByTestId('last3-tile')).map((t) => t.textContent)).toEqual(['Jul$800', 'Aug$0', 'Sep$0']);
  });

  it('a category with nothing this month says so', async () => {
    stubFetch({ ...ROUTES, '/api/transactions': NONE });
    open('/spending/travel?month=2026-10');
    expect(await screen.findByTestId('cat-total')).toHaveTextContent('$0');
    expect(screen.getAllByText('Nothing in Travel in October 2026.').length).toBeGreaterThan(0);
  });

  it('without a target it says what was spent and does not judge it (ruling 26)', async () => {
    stubFetch({ ...ROUTES, '/api/transactions': NONE });
    open('/spending/personal?month=2026-10');
    expect(await screen.findByTestId('cat-total')).toHaveTextContent(/^\$84$/);
    expect(screen.getByTestId('cat-state')).toHaveTextContent('No target · typically $90 a month');
    expect(document.querySelector('.sp-cat-head .sp-pace__bar')).toBeNull();
    const state = screen.getByTestId('cat-state');
    expect(state).not.toHaveTextContent(/over|ahead|track/i);
    expect(screen.getByRole('link', { name: 'Set a target' })).toBeInTheDocument();
    expect(screen.queryByText(/Over the target/)).toBeNull();
    expect(document.querySelectorAll('.sp-last3 .is-over')).toHaveLength(0);
  });

  it("a past month asks for that month's range and reads its pace as finished", async () => {
    const fetchMock = stubFetch({ ...ROUTES, '/api/spending': SEP, '/api/transactions': NONE });
    open('/spending/dining?month=2026-09');
    expect(await screen.findByText('Eating out · September 2026')).toBeInTheDocument();
    expect(screen.getByTestId('cat-state')).toHaveTextContent('$10 to spare');
    expect(screen.getByRole('heading', { name: 'Transactions in September 2026' })).toBeInTheDocument();
    await waitFor(() => expect(callsTo(fetchMock, 'GET', '/api/transactions')).toHaveLength(1));
    expect(callsTo(fetchMock, 'GET', '/api/transactions')[0].url).toContain('from=2026-09-01&to=2026-09-30');
    const tiles = await screen.findAllByTestId('last3-tile');
    expect(tiles.map((t) => t.textContent?.slice(0, 3))).toEqual(['Jun', 'Jul', 'Aug']);
  });

  it("with no month asked, the month is the server's, not the browser's", async () => {
    const fetchMock = stubFetch({ ...ROUTES, '/api/transactions': NONE });
    open('/spending/dining');
    expect(await screen.findByText('Eating out · October 2026')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'GET', '/api/spending').find((c) => !c.url.includes('/trends'))!.url).toBe('/api/spending');
    expect(screen.getByRole('link', { name: 'Spending' })).toHaveAttribute('href', '/b/ours/spending');
  });

  it('a viewer cannot change the target from here', async () => {
    stubFetch(ROUTES);
    open('/spending/dining?month=2026-10', { role: 'viewer' });
    await screen.findByTestId('cat-total');
    expect(screen.queryByRole('link', { name: 'Change the target' })).toBeNull();
    expect(screen.queryByRole('link', { name: 'Set a target' })).toBeNull();
  });

  it.each(['income', 'transfer', 'nope'])('/spending/%s is not a spending category: a plain line back to Spending, no crash', async (name) => {
    const fetchMock = stubFetch(ROUTES);
    const { location } = open(`/spending/${name}?month=2026-10`);
    expect(await screen.findByText(/is not a category Spending tracks/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Spending' })).toHaveAttribute('href', '/b/ours/spending?month=2026-10');
    expect(location.current.pathname).toBe(`/b/ours/spending/${name}`);
    expect(callsTo(fetchMock, 'GET', '/api')).toHaveLength(0);
  });

  it('a month the server refuses says so, with a way back', async () => {
    stubFetch({ ...ROUTES, '/api/spending': () => reply({ error: 'Month must be YYYY-MM.' }, 422) });
    open('/spending/dining?month=bad');
    expect(await screen.findByRole('alert')).toHaveTextContent('Month must be YYYY-MM.');
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
  });

  it('every state has exactly one h1', async () => {
    stubFetch({ ...ROUTES, '/api/spending': () => new Promise(() => {}) });
    const a = open('/spending/dining?month=2026-10');
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('October 2026');
    a.unmount();
    stubFetch(ROUTES);
    const b = open('/spending/dining?month=2026-10');
    await screen.findByTestId('cat-total');
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    b.unmount();
    open('/spending/nope');
    expect(await screen.findByRole('heading', { level: 1, name: 'Spending' })).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
  });

  it('a failed transactions fetch is an error with Try again, not an empty month', async () => {
    stubFetch({ ...ROUTES, '/api/transactions': () => reply({ error: 'Could not read transactions.' }, 500) });
    open('/spending/dining?month=2026-10');
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not read transactions.');
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
    expect(screen.queryByText('Nothing in Eating out in October 2026.')).toBeNull();
    expect(screen.getByTestId('cat-total')).toHaveTextContent('$468 of $500');
  });

  it('a failed next page keeps the rows shown and offers Try again below them', async () => {
    let n = 0;
    stubFetch({ ...ROUTES, '/api/transactions': () => (n++ === 0
      ? reply({ transactions: TXNS.transactions.slice(0, 2), next_cursor: 'c2' })
      : reply({ error: 'Could not read more.' }, 500)) });
    open('/spending/dining?month=2026-10');
    await waitFor(() => expect(screen.getAllByTestId('cat-txn')).toHaveLength(2));
    fireEvent.click(screen.getByRole('button', { name: 'Show more' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not read more.');
    expect(screen.getAllByTestId('cat-txn')).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('when the last months fail to load it says so, and the rest of the page stays', async () => {
    stubFetch({ ...ROUTES, '/api/spending/trends': () => reply({ error: 'no' }, 500) });
    open('/spending/dining?month=2026-10');
    expect(await screen.findByText('The last months could not be loaded.')).toBeInTheDocument();
    expect(screen.getByTestId('cat-total')).toHaveTextContent('$468 of $500');
  });
});

describe('Ask about this on a category (Surfaces)', () => {
  afterEach(() => { resetAsk(); });
  it('asks about the category and month; over target this month, the first question says so', async () => {
    stubFetch(ROUTES);
    open('/spending/shopping?month=2026-10', { chat: true });
    fireEvent.click(await screen.findByRole('button', { name: 'Ask about Shopping' }));
    expect(askState().about).toStrictEqual({ kind: 'category', category: 'shopping', month: '2026-10' });
    expect(askState().surface).toStrictEqual({ kind: 'category', category: 'shopping', month: '2026-10', over: true });
  });
  it('a category within its target is not over', async () => {
    stubFetch(ROUTES);
    open('/spending/dining?month=2026-10', { chat: true });
    fireEvent.click(await screen.findByRole('button', { name: 'Ask about Eating out' }));
    expect(askState().surface).toStrictEqual({ kind: 'category', category: 'dining', month: '2026-10', over: false });
  });
  it('no button with chat off', async () => {
    stubFetch(ROUTES);
    open('/spending/dining?month=2026-10');
    await screen.findByTestId('cat-total');
    expect(document.querySelector('.ask-about')).toBeNull();
  });
});
