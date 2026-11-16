import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Txn } from '../../api/types';
import { callsTo, stubFetch, wrapBook } from '../../test-utils';
import { ReviewCard } from './ReviewCard';

beforeEach(() => { localStorage.clear(); localStorage.setItem('steward-celebrations', 'off'); });
afterEach(() => vi.unstubAllGlobals());

const TXN: Txn = {
  id: 7, account_id: 1, account_name: 'Checking', posted_at: '2026-10-07', amount_cents: -1399,
  raw_description: 'PAYPAL *DISNEYPLUS', merchant: 'PayPal', category: 'uncategorized', is_business: false,
  is_transfer: false, business_pct: 0, business_line: null, business_source: 'none', category_source: 'none',
  reviewed_at: null, from_bank: true, matching: 0, reimburser_id: null, reimburse_ok: false, reason: 'p2p',
};
const VIEW = { nickname: null, reach: { others: 11, payee: 'PayPal', amount_cents: -1399, generic: true }, rule: null };
const noop = () => {};
const card = (txn: Txn = TXN, book = {}, more = {}) => wrapBook(
  <ReviewCard txn={txn} chips={['shopping', 'subscriptions']} today={new Date(2026, 9, 13)} onBegin={() => 'e1'}
    onDone={noop} onFail={noop} onNote={noop} {...more} />, book);

describe('a note from a Review card (P38)', () => {
  it('Note opens the form under the chips; saving keeps the card, unsorted, and hands the toast to Review', async () => {
    const onDone = vi.fn();
    const onNote = vi.fn();
    const fetchMock = stubFetch({ '/api/reimburse/payers': { payers: [] }, '/api/transactions/7/label': VIEW,
      'PUT /api/transactions/7/label': { rows: 12, notes_added: 12, named: 12, rule_id: null, undo: 'tok-r' } });
    card(TXN, {}, { onDone, onNote });
    fireEvent.click(screen.getByRole('button', { name: 'Note' }));
    const form = await screen.findByTestId('note-form');
    const chips = screen.getByRole('group', { name: 'Category' });
    expect(chips.compareDocumentPosition(form) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const also = await within(form).findByLabelText('Also the 11 PayPal $13.99 ones');
    expect(also).not.toBeChecked();                                     // a quick note stays on its own row
    fireEvent.change(within(form).getByLabelText('Name'), { target: { value: 'Disney+' } });
    expect(also).toBeChecked();                                         // a name reaches the rows like it
    fireEvent.click(within(form).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(onNote).toHaveBeenCalledWith(TXN, 'tok-r', 'Saved on 12'));
    expect(screen.queryByTestId('note-form')).toBeNull();                 // the form closes; Review's toast has the Undo
    expect(document.querySelector('.undo-toast')).toBeNull();
    expect(callsTo(fetchMock, 'PUT', '/api/transactions/7/label')[0].body).toEqual({ note: null, nickname: 'Disney+', also: true, future: false });
    expect(screen.getByTestId('review-card')).toBeInTheDocument();
    expect(onDone).not.toHaveBeenCalled();
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/7')).toHaveLength(0);       // a note never sorts it
  });

  it('a note alone from the card stays on its row: Also starts unticked', async () => {
    const fetchMock = stubFetch({ '/api/reimburse/payers': { payers: [] }, '/api/transactions/7/label': VIEW,
      'PUT /api/transactions/7/label': { rows: 1, notes_added: 1, named: 0, rule_id: null, undo: 'tok-s' } });
    const onNote = vi.fn();
    card(TXN, {}, { onNote });
    fireEvent.click(screen.getByRole('button', { name: 'Note' }));
    const form = await screen.findByTestId('note-form');
    expect(await within(form).findByLabelText('Also the 11 PayPal $13.99 ones')).not.toBeChecked();
    fireEvent.change(within(form).getByLabelText('Note'), { target: { value: 'Asked Sam about this one' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(onNote).toHaveBeenCalledWith(TXN, 'tok-s', 'Saved'));
    expect(callsTo(fetchMock, 'PUT', '/api/transactions/7/label')[0].body).toEqual(
      { note: 'Asked Sam about this one', nickname: null, also: false, future: false });
  });

  it('Escape or Cancel closes the form', async () => {
    stubFetch({ '/api/reimburse/payers': { payers: [] }, '/api/transactions/7/label': VIEW });
    card();
    fireEvent.click(screen.getByRole('button', { name: 'Note' }));
    fireEvent.keyDown(await screen.findByLabelText('Note'), { key: 'Escape' });
    await waitFor(() => expect(screen.queryByTestId('note-form')).toBeNull());
    fireEvent.click(screen.getByRole('button', { name: 'Note' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByTestId('note-form')).toBeNull());
  });

  it('a named row reads "Disney+ (PayPal)"', () => {
    stubFetch({ '/api/reimburse/payers': { payers: [] } });
    card({ ...TXN, nickname: 'Disney+' });
    expect(screen.getByTestId('review-card').querySelector('.rcard__desc')).toHaveTextContent('Disney+ (PayPal)');
  });

  it('has no Note while picking, for a viewer, or in a parent book', () => {
    stubFetch({ '/api/reimburse/payers': { payers: [] } });
    const { unmount } = card(TXN, {}, { selecting: true });
    expect(screen.queryByRole('button', { name: 'Note' })).toBeNull();
    unmount();
    const viewer = card(TXN, { role: 'viewer' });
    expect(screen.queryByRole('button', { name: 'Note' })).toBeNull();
    viewer.unmount();
    card(TXN, { kind: 'parent' });
    expect(screen.queryByRole('button', { name: 'Note' })).toBeNull();
  });
});
