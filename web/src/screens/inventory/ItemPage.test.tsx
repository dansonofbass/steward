import { fireEvent, screen, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, expectRemovalSaid, reply, stubFetch, wrapBook } from '../../test-utils';
import type { ItemDetail } from './api';
import { ItemPage } from './ItemPage';

afterEach(() => vi.unstubAllGlobals());
const PARENT = { slug: 'margaret-ellis', name: 'Margaret Ellis', kind: 'parent' as const, owners: [] };
const base: ItemDetail = {
  id: 12, kind: 'insurance', name: 'Long-term care', owner: 'margaret', owner_label: 'Margaret', institution: 'Evergreen Mutual',
  last4: '7730', status: 'needs_checking', data_source: 'manual', type: 'long_term_care', type_label: 'Long-term care',
  type_word: 'long-term care', sub: 'Evergreen Mutual · policy ••7730', amount_cents: 21200, amount_per: 'mo', monthly_cents: 21200,
  counts_in_totals: true, no_balance: false, total_group: null, updated_on: '2026-10-12',
  check_reason: 'Typed in from a premium notice found in the mail.', account_id: null,
  details: { type: 'long_term_care', amount_cents: 21200, frequency: 'monthly', usual_day: 10 }, login_kept_in: null, notes: null,
  has_full_number: true, closed_on: null, closed_reason: null,
  refs: { lands_in_id: null, paid_from_id: { id: 1, label: 'Wells Fargo Joint checking ••4417' }, prepared_by_id: null },
  looks_after: [], money_in_here: [], paid_from_here: [], linked_items: [], joint_names: null, added_line: 'Oct 12 by Jr',
  balance: null, holdings: null, transactions: [], matched: { heading: 'Last 1 payments', match_text: 'EVERGREEN MUTUAL', rows: [{ posted_at: '2026-10-09', amount_cents: -21200, note: null }], last_paid: '2026-10-09' },
  files: [{ id: 5, name: 'Premium notice.pdf', content_type: 'application/pdf', label: 'PDF', size: 96000, size_label: '94 KB', uploaded_on: '2026-10-12', uploaded_by: 'Jr' }],
  history: [{ id: 'c1', at: '2026-10-12T20:00:00+00:00', who: 'Jr', icon: 'plus', text: 'added this item', item: null, diffs: [], lines: ['Needs checking'], note: null, summary: 'Jr added Long-term care' }],
};
const page = (_detail: ItemDetail, book = PARENT) =>
  wrapBook(<Routes><Route path="/b/:slug/inventory/:id" element={<ItemPage />} /></Routes>, book, '/b/margaret-ellis/inventory/12');

describe('Item page', () => {
  it('shows a policy, reveals its number and confirms it', async () => {
    const fetchMock = stubFetch({
      '/api/inventory/items/12': base,
      'POST /api/inventory/items/12/full-number': () => reply({ number: 'EM-LTC-0047730' }),
      'PATCH /api/inventory/items/12': () => reply({ ...base, status: 'confirmed', check_reason: null }),
    });
    page(base);
    expect(await screen.findByRole('heading', { name: 'Long-term care' })).toBeInTheDocument();
    expect(screen.getByText('Insurance · long-term care')).toBeInTheDocument();
    expect(screen.getByText('Typed in from a premium notice found in the mail.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Wells Fargo Joint checking ••4417' })).toHaveAttribute('href', '/b/margaret-ellis/inventory/1');
    expect(screen.getByText('••7730')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Show' }));
    expect(await screen.findByText('EM-LTC-0047730')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Hide' }));
    expect(screen.queryByText('EM-LTC-0047730')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Mark Confirmed' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/inventory/items/12')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PATCH', '/api/inventory/items/12')[0].body).toEqual({ status: 'confirmed' });
    expect(screen.getByRole('link', { name: 'Download Premium notice.pdf' })).toHaveAttribute('href', '/api/b/margaret-ellis/inventory/files/5');
  });
  it('a viewer gets no Edit, Attach or Remove, and a worded Download', async () => {
    stubFetch({ '/api/inventory/items/12': base });
    page(base, { ...PARENT, role: 'viewer' } as typeof PARENT);
    expect(await screen.findByRole('heading', { name: 'Long-term care' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Edit/ })).toBeNull();
    expect(screen.queryByRole('link', { name: /Attach/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Remove/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Mark Confirmed' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Show' })).toBeInTheDocument();   // viewers may reveal (decision 5)
    expect(within(screen.getByRole('region', { name: 'Files' })).getByRole('link', { name: /Download/ })).toHaveTextContent('Download');
  });
  it('a closed item can be reopened', async () => {
    const closed = { ...base, status: 'closed' as const, closed_on: '2025-02-14', closed_reason: 'Policy cancelled' };
    const fetchMock = stubFetch({ '/api/inventory/items/12': closed, 'POST /api/inventory/items/12/reopen': () => reply({ ...closed, status: 'confirmed' }) });
    page(closed);
    expect(await screen.findByText(/Closed Feb 14, 2025\. Policy cancelled/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reopen' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/inventory/items/12/reopen')).toHaveLength(1));
  });
  it('a revealed number does not follow a link to another item', async () => {
    const wells: ItemDetail = {
      ...base, id: 1, kind: 'account', name: 'Wells Fargo Joint checking', institution: 'Wells Fargo', last4: '4417', type: 'checking',
      type_label: 'Checking', type_word: 'checking', status: 'confirmed', check_reason: null, has_full_number: true,
      refs: { lands_in_id: null, paid_from_id: null, prepared_by_id: null }, matched: null, files: [], history: [], details: { type: 'checking' },
    };
    stubFetch({
      '/api/inventory/items/12': base,
      '/api/inventory/items/1': wells,
      'POST /api/inventory/items/12/full-number': () => reply({ number: 'EM-LTC-0047730' }),
    });
    page(base);
    fireEvent.click(await screen.findByRole('button', { name: 'Show' }));
    expect(await screen.findByText('EM-LTC-0047730')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: 'Wells Fargo Joint checking ••4417' }));
    expect(await screen.findByRole('heading', { name: 'Wells Fargo Joint checking' })).toBeInTheDocument();
    expect(screen.queryByText('EM-LTC-0047730')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Hide' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Show' })).toBeInTheDocument();
  });
  it("shows an account item's low-balance floor", async () => {
    const account = { ...base, id: 12, kind: 'account' as const, type: 'savings', type_label: 'Savings', details: { type: 'savings', floor_cents: 2500000 },
      matched: null, balance: { cents: 2248010, line: 'From the bank feed, today, 6:10 AM' } };
    stubFetch({ '/api/inventory/items/12': account });
    page(account);
    expect(await screen.findByText('Low-balance floor')).toBeInTheDocument();
    expect(screen.getByText('$25,000.00')).toBeInTheDocument();
  });
  it('shows the holdings a statement brought, read-only', async () => {
    const account = { ...base, id: 12, kind: 'account' as const, type: 'ira', type_label: 'IRA', details: { type: 'ira' }, matched: null,
      balance: { cents: 8421033, line: 'From a statement' },
      holdings: { as_of: '2026-03-31', rows: [{ symbol: 'VTSAX', name: 'Total Stock Market', value_cents: 5230120 }, { symbol: null, name: 'Cash', value_cents: 3190913 }] } };
    stubFetch({ '/api/inventory/items/12': account });
    page(account);
    const held = within(await screen.findByRole('region', { name: 'Holdings on Mar 31, 2026' }));
    expect(held.getByRole('heading', { name: 'Holdings on Mar 31, 2026' })).toBeInTheDocument();
    expect(held.getByText('VTSAX')).toBeInTheDocument();
    expect(held.getByText('$31,909.13')).toBeInTheDocument();
    expect(held.queryByRole('button')).toBeNull();
    expect(held.queryByRole('textbox')).toBeNull();
  });
  it('a manager sees the words Download and Remove beside the icons on each file', async () => {
    stubFetch({ '/api/inventory/items/12': base });
    page(base);
    const files = within(await screen.findByRole('region', { name: 'Files' }));
    expect(files.getByRole('link', { name: 'Download Premium notice.pdf' })).toHaveTextContent(/^Download/);
    expect(files.getByRole('button', { name: 'Remove Premium notice.pdf' })).toHaveTextContent(/^Remove/);
  });
  it('removing a file asks first and sends nothing until Remove', async () => {
    const fetchMock = stubFetch({ '/api/inventory/items/12': base, 'DELETE /api/inventory/files/5': () => new Response(null, { status: 204 }) });
    page(base);
    const files = within(await screen.findByRole('region', { name: 'Files' }));
    fireEvent.click(files.getByRole('button', { name: 'Remove Premium notice.pdf' }));
    const ask = screen.getByRole('dialog', { name: 'Remove Premium notice.pdf?' });
    expect(within(ask).getByText('It comes off this item. The change record keeps a line saying so.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'DELETE', '/api/inventory/files')).toHaveLength(0);
    fireEvent.click(within(ask).getByRole('button', { name: 'Keep it' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(callsTo(fetchMock, 'DELETE', '/api/inventory/files')).toHaveLength(0);
    fireEvent.click(files.getByRole('button', { name: 'Remove Premium notice.pdf' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/inventory/files/5')).toHaveLength(1));
  });
  it('after removing a file, says which and keeps focus on Files, not the gone row (THO-1)', async () => {
    let item = base;
    stubFetch({ '/api/inventory/items/12': () => reply(item),
      'DELETE /api/inventory/files/5': () => { item = { ...base, files: [] }; return new Response(null, { status: 204 }); } });
    page(base);
    const files = within(await screen.findByRole('region', { name: 'Files' }));
    const button = files.getByRole('button', { name: 'Remove Premium notice.pdf' });
    button.focus();
    fireEvent.click(button);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
    await expectRemovalSaid('Removed Premium notice.pdf.', () => screen.getByRole('heading', { name: 'Files' }));
    expect(await screen.findByText('No files yet.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Files' })).toHaveFocus();
  });
  it('only an insurance item is told to attach the policy', async () => {
    const account: ItemDetail = { ...base, kind: 'account', type: 'checking', type_label: 'Checking', details: {}, matched: null };
    stubFetch({ '/api/inventory/items/12': account });
    page(account);
    await screen.findByRole('heading', { name: 'Long-term care' });
    expect(screen.getByText(/attach a recent statement/i)).toBeInTheDocument();
    expect(screen.queryByText(/policy/i)).toBeNull();
  });
  it('payments of the same amount on the same day each get a row without a key warning', async () => {
    const twice = { ...base, matched: { ...base.matched!, rows: [
      { posted_at: '2026-10-09', amount_cents: -21200, note: null }, { posted_at: '2026-10-09', amount_cents: -21200, note: 'again' }] } };
    const warn = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    stubFetch({ '/api/inventory/items/12': twice });
    page(twice);
    await screen.findByRole('heading', { name: 'Long-term care' });
    expect(screen.getByText('(again)')).toBeInTheDocument();
    expect(warn.mock.calls.flat().join(' ')).not.toMatch(/same key/);
    warn.mockRestore();
  });
  it('an unknown premium frequency still shows the page', async () => {
    const odd = { ...base, details: { ...base.details, frequency: 'weekly' } };
    stubFetch({ '/api/inventory/items/12': odd });
    page(odd);
    expect(await screen.findByRole('heading', { name: 'Long-term care' })).toBeInTheDocument();
    expect(screen.getByText('weekly', { exact: false })).toBeInTheDocument();
  });

  it('shows the benefit terms of a long-term care policy', async () => {
    const ltc: ItemDetail = { ...base, details: { ...base.details, benefit_cents: 15000, benefit_per: 'day', waiting_days: 90, benefit_years: 3, rider_bp: 300 } };
    stubFetch({ '/api/inventory/items/12': ltc });
    page(ltc);
    expect(await screen.findByText('90 days')).toBeInTheDocument();
    expect(screen.getByText('$150.00')).toBeInTheDocument();
    expect(screen.getByText('3 years of benefit')).toBeInTheDocument();
    expect(screen.getByText('3% a year')).toBeInTheDocument();
  });
});
