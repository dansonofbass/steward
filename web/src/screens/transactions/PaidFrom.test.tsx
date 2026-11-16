import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Txn } from '../../api/types';
import { callsTo, stubFetch, wrapBook } from '../../test-utils';
import { LIST, PROPTAX_DETAIL } from '../spending/setasides/fixtures';
import { PaidFrom } from './PaidFrom';

afterEach(() => vi.unstubAllGlobals());
const TXN: Txn = {
  id: 7, account_id: 1, account_name: 'Checking', posted_at: '2026-11-01', amount_cents: -421_000, raw_description: 'COUNTY TAX COLLECTOR',
  merchant: 'County Tax Collector', category: 'taxes', is_business: false, is_transfer: false, business_pct: 0, business_line: null,
  business_source: 'none', category_source: 'rule', reviewed_at: null, from_bank: true, set_aside: null,
};
const MATCHED = { id: 1, name: 'Property tax', how: 'auto' as const, archived: false };

describe('Paid from a set-aside, on a transaction', () => {
  it('offers the active set-asides for money out, and matching sends the pair', async () => {
    const onSaved = vi.fn();
    const fetchMock = stubFetch({ '/api/setasides': LIST, 'POST /api/setasides/match': PROPTAX_DETAIL });
    wrapBook(<PaidFrom txn={TXN} onSaved={onSaved} />);
    fireEvent.click(screen.getByRole('button', { name: 'Paid from a set-aside' }));
    const group = await screen.findByRole('group', { name: 'Which set-aside paid it?' });
    const options = Array.from(group.querySelectorAll('button'));
    expect(options.map((b) => b.textContent)).toEqual(LIST.rows.map((r) => r.name));
    fireEvent.click(options[0]);
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/setasides/match')[0].body).toEqual({ transaction_id: 7, set_aside_id: LIST.rows[0].id }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ ...TXN, set_aside: { id: LIST.rows[0].id, name: LIST.rows[0].name, how: 'hand', archived: false } }));
  });

  it('a matched payment says so and offers Not this one, refreshing through invalidateSetAsides', async () => {
    const onSaved = vi.fn();
    const fetchMock = stubFetch({ 'DELETE /api/setasides/match/7': () => new Response(null, { status: 204 }) });
    const { qc } = wrapBook(<PaidFrom txn={{ ...TXN, set_aside: MATCHED }} onSaved={onSaved} />);
    const spy = vi.spyOn(qc, 'invalidateQueries');
    expect(screen.getByTestId('paid-from')).toHaveTextContent('Paid from Setting aside: Property tax');
    expect(screen.getByRole('link', { name: 'Property tax' })).toHaveAttribute('href', '/b/ours/spending/setasides/1');
    fireEvent.click(screen.getByRole('button', { name: 'Not this one' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/setasides/match/7')).toHaveLength(1));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ ...TXN, set_aside: null }));
    for (const k of ['spending', 'setasides', 'plan', 'transactions', 'summary']) expect(spy).toHaveBeenCalledWith({ queryKey: [k] });
  });

  it('a stopped set-aside keeps its match: no Not this one', () => {
    stubFetch({});
    wrapBook(<PaidFrom txn={{ ...TXN, set_aside: { ...MATCHED, archived: true } }} onSaved={() => {}} />);
    expect(screen.getByTestId('paid-from')).toHaveTextContent('Paid from Setting aside: Property tax');
    expect(screen.queryByRole('button', { name: 'Not this one' })).toBeNull();
  });

  it('shows nothing for money in, a transfer, a parent book, or a viewer with no match', () => {
    stubFetch({ '/api/setasides': LIST });
    const { unmount } = wrapBook(<PaidFrom txn={{ ...TXN, amount_cents: 5_000 }} onSaved={() => {}} />);
    expect(screen.queryByRole('button', { name: 'Paid from a set-aside' })).toBeNull();
    unmount();
    const t = wrapBook(<PaidFrom txn={{ ...TXN, is_transfer: true }} onSaved={() => {}} />);
    expect(screen.queryByRole('button', { name: 'Paid from a set-aside' })).toBeNull();
    t.unmount();
    const p = wrapBook(<PaidFrom txn={TXN} onSaved={() => {}} />, { slug: 'mom', kind: 'parent' });
    expect(screen.queryByRole('button', { name: 'Paid from a set-aside' })).toBeNull();
    p.unmount();
    wrapBook(<PaidFrom txn={TXN} onSaved={() => {}} />, { role: 'viewer' });
    expect(screen.queryByRole('button', { name: 'Paid from a set-aside' })).toBeNull();
  });

  it('a viewer sees the match but cannot undo it', () => {
    stubFetch({});
    wrapBook(<PaidFrom txn={{ ...TXN, set_aside: MATCHED }} onSaved={() => {}} />, { role: 'viewer' });
    expect(screen.getByTestId('paid-from')).toHaveTextContent('Paid from Setting aside: Property tax');
    expect(screen.queryByRole('button', { name: 'Not this one' })).toBeNull();
  });
});
