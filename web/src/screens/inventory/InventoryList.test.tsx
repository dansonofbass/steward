import { fireEvent, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { stubFetch, wrapBook } from '../../test-utils';
import type { ItemRow } from './api';
import { InventoryList } from './InventoryList';

afterEach(() => vi.unstubAllGlobals());
const OWNERS = [{ key: 'margaret', label: 'Margaret' }, { key: 'robert-husband', label: 'Robert (husband)' }, { key: 'joint', label: 'Joint' }];
const PARENT = { slug: 'margaret-ellis', name: 'Margaret Ellis', kind: 'parent' as const, owners: OWNERS };
const row = (over: Partial<ItemRow>): ItemRow => ({
  id: 1, kind: 'account', name: 'Joint checking', owner: 'joint', owner_label: 'Joint', institution: 'Wells Fargo', last4: '4417',
  status: 'confirmed', data_source: 'feed', type: 'checking', type_label: 'Checking', type_word: 'checking',
  sub: 'Wells Fargo · checking ••4417', amount_cents: 821455, amount_per: null, monthly_cents: null, counts_in_totals: true,
  no_balance: false, total_group: 'cash', updated_on: '2026-09-30', check_reason: null, account_id: 3, ...over,
});
const ITEMS = [
  row({}),
  row({ id: 2, name: 'Deferred annuity', institution: 'Westmark Life', last4: '5521', owner: 'margaret', owner_label: 'Margaret', status: 'needs_checking', data_source: 'manual', sub: 'Westmark Life · annuity ••5521', amount_cents: null, no_balance: true }),
  row({ id: 3, kind: 'insurance', name: 'Long-term care', institution: 'Evergreen Mutual', owner: 'margaret', owner_label: 'Margaret', status: 'needs_checking', data_source: 'manual', sub: 'Evergreen Mutual · policy ••7730', amount_cents: 21200, amount_per: 'mo', monthly_cents: 21200 }),
  row({ id: 4, name: 'Savings', institution: 'Chase', status: 'closed', sub: 'Chase · savings ••6630 · closed Feb 2025', amount_cents: 0 }),
];
const SUGG = { count: 3, found_in: 'found in the transactions', phrases: ['an annuity deposit', 'a Medicare supplement premium', 'interest from Harbor Savings Bank'] };

describe('Inventory list', () => {
  it('groups items, counts statuses and filters', async () => {
    stubFetch({ '/api/inventory': { items: ITEMS, suggestions: SUGG } });
    wrapBook(<InventoryList />, PARENT, '/b/margaret-ellis/inventory');
    expect(await screen.findByRole('heading', { name: 'Inventory' })).toBeInTheDocument();
    expect(screen.getByText('Everything Margaret has, where it is, and how sure we are about each one.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Add an item/ })).toHaveAttribute('href', '/b/margaret-ellis/inventory/new');
    expect(screen.getByText(/Is this one of Margaret.s\?/)).toBeInTheDocument();
    expect(screen.getByText('· an annuity deposit, a Medicare supplement premium, interest from Harbor Savings Bank')).toBeInTheDocument();
    const all = screen.getByRole('link', { name: 'All transactions' });
    expect(all).toHaveAttribute('href', '/b/margaret-ellis/transactions?dates=all');
    expect(all.compareDocumentPosition(screen.getByRole('region', { name: 'Accounts' })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const status = screen.getByRole('group', { name: 'Status' });
    expect(within(status).getByRole('button', { name: /^All 4$/ })).toHaveAttribute('aria-pressed', 'true');
    expect(within(screen.getByRole('region', { name: 'Accounts' })).getByText('No balance yet')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Policies' })).getByText('$212.00 /mo')).toBeInTheDocument();
    fireEvent.click(within(status).getByRole('button', { name: /^Needs checking 2$/ }));
    expect(screen.queryByText('Joint checking')).toBeNull();
    expect(screen.getByText('To confirm an item, open it and attach a statement or letter, or link it to an account in the bank feed.')).toBeInTheDocument();
    fireEvent.click(within(status).getByRole('button', { name: /^All 4$/ }));
    fireEvent.change(screen.getByLabelText('Search'), { target: { value: '7730' } });
    expect(screen.getAllByTestId('item-row').map((r) => r.textContent)).toEqual([expect.stringContaining('Long-term care')]);
  });
  it('opens filtered to Needs checking from Home', async () => {
    stubFetch({ '/api/inventory': { items: ITEMS, suggestions: null } });
    wrapBook(<InventoryList />, PARENT, '/b/margaret-ellis/inventory?status=needs_checking');
    expect(await screen.findByText('Deferred annuity')).toBeInTheDocument();
    expect(screen.queryByText('Joint checking')).toBeNull();
  });
  it('a viewer sees the list and nothing to change', async () => {
    stubFetch({ '/api/inventory': { items: ITEMS, suggestions: SUGG } });
    wrapBook(<InventoryList />, { ...PARENT, role: 'viewer' }, '/b/margaret-ellis/inventory');
    expect(await screen.findByText('You can see this book but not change it.')).toBeInTheDocument();
    expect(screen.getByText('Deferred annuity')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Add an item/ })).toBeNull();
    expect(screen.queryByText(/Is this one of Margaret.s\?/)).toBeNull();
  });
});
