import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BookSummary } from '../api/types';
import { BOOK, callsTo, stubFetch, wrapBook } from '../test-utils';
import { ACCTS } from './accounts/fixtures';
import Transactions from './Transactions';

afterEach(() => { vi.unstubAllGlobals(); });

const ours: BookSummary = BOOK;
const mom: BookSummary = { ...BOOK, slug: 'mom', name: 'Mom', kind: 'parent' };
const ROW = { id: 1, account_id: 1, account_name: 'Checking', posted_at: '2026-10-10', amount_cents: -1200, raw_description: 'SQ *VENDOR', merchant: null, category: 'uncategorized', is_business: false, is_transfer: false, business_pct: 0, business_line: null, business_source: 'none', category_source: 'none', reviewed_at: null, from_bank: true, set_aside: null };
const EMPTY = { '/api/accounts': { accounts: ACCTS }, '/api/transactions': { transactions: [], next_cursor: null } };

describe('All transactions', () => {
  it('is titled All transactions with a back link to Accounts in a household', async () => {
    stubFetch(EMPTY);
    wrapBook(<Transactions />, ours, '/b/ours/transactions?dates=all');
    expect(await screen.findByRole('heading', { level: 1, name: 'All transactions' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Accounts/ })).toHaveAttribute('href', '/b/ours/accounts');
  });
  it('goes back to Inventory in a parent book', async () => {
    stubFetch(EMPTY);
    wrapBook(<Transactions />, mom, '/b/mom/transactions?dates=all');
    expect(await screen.findByRole('heading', { level: 1, name: 'All transactions' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Inventory/ })).toHaveAttribute('href', '/b/mom/inventory');
    expect(screen.queryByRole('link', { name: /Accounts/ })).toBeNull();
  });
  it('keeps the Account filter, from the address', async () => {
    const fetchMock = stubFetch(EMPTY);
    wrapBook(<Transactions />, ours, '/b/ours/transactions?dates=all&account_id=2');
    expect(await screen.findByRole('button', { name: 'Account: Rewards Card ••4402, clear' })).toBeInTheDocument();
    await waitFor(() => expect(callsTo(fetchMock, 'GET', '/api/transactions')[0]?.url).toContain('account_id=2'));
  });
});

describe('a named row (polish round P5)', () => {
  it('reads "Disney+ (PayPal)" in the list', async () => {
    stubFetch({ '/api/accounts': { accounts: ACCTS }, '/api/transactions': { transactions: [{ ...ROW, merchant: 'PayPal', nickname: 'Disney+' }], next_cursor: null } });
    wrapBook(<Transactions />, ours, '/b/ours/transactions?dates=all');
    expect(await screen.findByTestId('txn-row')).toHaveTextContent('Disney+ (PayPal)');
  });
});

describe('one account\'s transactions', () => {
  it('fixes the account, without a chip, a title or a back link of its own', async () => {
    const fetchMock = stubFetch(EMPTY);
    wrapBook(<Transactions accountId={3} head={<h1>Roth IRA</h1>} />, ours, '/b/ours/accounts/3?dates=all&account_id=2');
    expect(await screen.findByRole('heading', { level: 1, name: 'Roth IRA' })).toBeInTheDocument();
    await waitFor(() => expect(callsTo(fetchMock, 'GET', '/api/transactions')[0]?.url).toContain('account_id=3'));
    expect(screen.queryByRole('heading', { name: 'All transactions' })).toBeNull();
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.queryByRole('button', { name: /^Account/ })).toBeNull();
  });
});

describe('Sorted by (phase 12 decision 5)', () => {
  it('reads sorted= from the address, sends it to the API and shows it as a chip', async () => {
    const fetchMock = stubFetch(EMPTY);
    wrapBook(<Transactions />, ours, '/b/ours/transactions?dates=all&sorted=steward');
    expect(await screen.findByRole('button', { name: 'Sorted by: By Steward, not checked, clear' })).toBeInTheDocument();
    await waitFor(() => expect(callsTo(fetchMock, 'GET', '/api/transactions')[0]?.url).toContain('sorted=steward'));
  });
  it('offers the two choices', async () => {
    stubFetch(EMPTY);
    wrapBook(<Transactions />, ours, '/b/ours/transactions?dates=all');
    fireEvent.click(await screen.findByRole('button', { name: 'Sorted by' }));
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['By Steward, not checked', "Steward wasn't sure"]);
  });
  it('marks a row that has notes', async () => {
    stubFetch({ ...EMPTY, '/api/transactions': { transactions: [{ ...ROW, note_count: 2 }, { ...ROW, id: 2, note_count: 0 }], next_cursor: null } });
    wrapBook(<Transactions />, ours, '/b/ours/transactions?dates=all');
    const rows = await screen.findAllByTestId('txn-row');
    expect(within(rows[0]).getByText('2 notes')).toBeInTheDocument();
    expect(within(rows[1]).queryByText(/note/)).toBeNull();
  });
});
