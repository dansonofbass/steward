import type { QueryClient } from '@tanstack/react-query';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Txn } from '../../api/types';
import { callsTo, reply, stubFetch, wrapBook } from '../../test-utils';
import { ReviewCard } from './ReviewCard';

const onDone = vi.fn();
beforeEach(() => { localStorage.clear(); localStorage.setItem('steward-celebrations', 'off'); onDone.mockReset(); });
afterEach(() => vi.unstubAllGlobals());

const TXN: Txn = {
  id: 7, account_id: 1, account_name: 'Sapphire', posted_at: '2026-10-07', amount_cents: -41218,
  raw_description: 'HILTON CHICAGO IL', merchant: null, category: 'uncategorized', is_business: false,
  is_transfer: false, business_pct: 0, business_line: null, business_source: 'none', category_source: 'none',
  reviewed_at: null, from_bank: true, matching: null, reimburser_id: null, reimburse_ok: true,
};
const DEPOSIT: Txn = { ...TXN, id: 8, amount_cents: 33965, raw_description: 'ACME CORP EXP', reimburse_ok: false };
const ACME = { payers: [{ id: 1, name: 'Acme' }] };
const TWO = { payers: [{ id: 1, name: 'Acme' }, { id: 2, name: 'Globex' }] };
const MARKED = { change: 'marked', reimburser_id: 1, payer: 'Acme', was_cents: 82817, owed_cents: 124035 };
const sorted = (txn: Txn, category: string, reimburse: object) =>
  ({ ...txn, category, result: { category, applied: 0, rule: 'made', undo: 'tok', reimburse } });
const noop = () => {};
const card = (txn: Txn = TXN, chips = ['travel', 'dining'], book = {}) => wrapBook(
  <ReviewCard txn={txn} chips={chips} today={new Date(2026, 9, 13)} onBegin={() => 'e1'} onDone={onDone} onFail={noop} onNote={noop} />, book);
// A chip waits while nobody is chosen to pay (choice 20), so a test taps one only once the payers have arrived.
const loaded = (qc: QueryClient) => waitFor(() => expect(qc.getQueryData(['reimburse', 'payers'])).toBeDefined());

describe('the Reimbursable switch on a Review card (reimbursable spec, Marking)', () => {
  it('marks the charge with the sort and says what Acme owes', async () => {
    const fetchMock = stubFetch({ '/api/reimburse/payers': ACME, 'PATCH /api/transactions/7': sorted(TXN, 'travel', MARKED) });
    const { qc } = card();
    await loaded(qc);
    fireEvent.click(screen.getByRole('switch', { name: 'Reimbursable' }));
    fireEvent.click(screen.getByRole('button', { name: 'Travel' }));
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(onDone.mock.calls[0][2].reply.result.reimburse).toEqual(MARKED);
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/7')[0].body).toEqual({ category: 'travel', reimbursable: true });
  });

  it('the first time, asks who pays you back, then the mark applies', async () => {
    let payers: { id: number; name: string }[] = [];
    const fetchMock = stubFetch({
      '/api/reimburse/payers': () => reply({ payers }),
      'POST /api/reimburse/payers': () => { payers = [{ id: 1, name: 'Acme' }]; return reply(payers[0], 201); },
      'PATCH /api/transactions/7': sorted(TXN, 'travel', { ...MARKED, was_cents: 0, owed_cents: 41218 }),
    });
    card();
    fireEvent.click(screen.getByRole('switch', { name: 'Reimbursable' }));
    const box = await screen.findByPlaceholderText('Your employer, e.g. Acme');
    fireEvent.click(screen.getByRole('button', { name: 'Travel' }));                // waits: nobody to pay it back yet
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/7')).toHaveLength(0);
    fireEvent.change(box, { target: { value: 'Acme' } });
    fireEvent.click(within(screen.getByRole('group', { name: 'Who pays you back?' })).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(screen.queryByPlaceholderText('Your employer, e.g. Acme')).toBeNull());
    expect(callsTo(fetchMock, 'POST', '/api/reimburse/payers')[0].body).toEqual({ name: 'Acme' });
    fireEvent.click(screen.getByRole('button', { name: 'Travel' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/transactions/7')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/7')[0].body).toEqual({ category: 'travel', reimbursable: true });
  });

  it('with two payers, a chooser picks who, and it rides the PATCH', async () => {
    const fetchMock = stubFetch({ '/api/reimburse/payers': TWO, 'PATCH /api/transactions/7': sorted(TXN, 'travel', MARKED) });
    card();
    fireEvent.click(screen.getByRole('switch', { name: 'Reimbursable' }));
    const who = await screen.findByRole('combobox', { name: 'Who pays you back?' });
    fireEvent.click(screen.getByRole('button', { name: 'Travel' }));
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/7')).toHaveLength(0);
    fireEvent.change(who, { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Travel' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/transactions/7')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/7')[0].body).toEqual({ category: 'travel', reimbursable: true, reimburser_id: 2 });
  });

  it('turns Business off and says why, and the other way round', () => {
    stubFetch({ '/api/reimburse/payers': ACME });
    card();
    const business = screen.getByRole('switch', { name: 'Business' });
    const reimb = screen.getByRole('switch', { name: 'Reimbursable' });
    fireEvent.click(business);
    fireEvent.click(reimb);
    expect([business.getAttribute('aria-checked'), reimb.getAttribute('aria-checked')]).toEqual(['false', 'true']);
    expect(screen.getByText('A charge is either business or reimbursable.')).toBeInTheDocument();
    fireEvent.click(business);
    expect([business.getAttribute('aria-checked'), reimb.getAttribute('aria-checked')]).toEqual(['true', 'false']);
  });

  it('a repayment rides the PATCH with its payer and hands back what it did to the balance', async () => {
    stubFetch({ '/api/reimburse/payers': ACME,
      'PATCH /api/transactions/8': sorted(DEPOSIT, 'reimbursement', { change: 'repaid', reimburser_id: 1, payer: 'Acme', was_cents: 40000, owed_cents: 6035 }) });
    const { qc } = card(DEPOSIT, ['reimbursement', 'income']);
    expect(screen.queryByRole('switch', { name: 'Reimbursable' })).toBeNull();      // money in, nothing reimbursable from it
    await loaded(qc);
    fireEvent.click(screen.getByRole('button', { name: 'Reimbursement' }));
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(onDone.mock.calls[0][2]).toMatchObject({ kind: 'sort', category: 'reimbursement' });
    expect(onDone.mock.calls[0][2].reply.result.reimburse.change).toBe('repaid');
  });

  it('has no switch in a parent book', () => {
    stubFetch({});
    card(TXN, ['travel'], { kind: 'parent' });
    expect(screen.queryByRole('switch', { name: 'Reimbursable' })).toBeNull();
  });
});
