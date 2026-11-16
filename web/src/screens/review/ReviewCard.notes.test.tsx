import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Txn } from '../../api/types';
import { callsTo, ME, reply, stubFetch, wrapBook } from '../../test-utils';
import { ReviewCard } from './ReviewCard';

beforeEach(() => { localStorage.clear(); localStorage.setItem('steward-celebrations', 'off'); });
afterEach(() => vi.unstubAllGlobals());

const TXN: Txn = {
  id: 7, account_id: 1, account_name: 'Checking', posted_at: '2026-10-07', amount_cents: -1399,
  raw_description: 'PAYPAL *DISNEYPLUS', merchant: 'PayPal', category: 'uncategorized', is_business: false,
  is_transfer: false, business_pct: 0, business_line: null, business_source: 'none', category_source: 'none',
  reviewed_at: null, from_bank: true, matching: 0, reimburser_id: null, reimburse_ok: false, reason: 'p2p', note_count: 2,
};
const NOTES = { notes: [
  { id: 1, author_id: 1, author_name: 'JR', body: 'Water heater, half paid by Sam', created_at: '2026-10-11T18:00:00+00:00' },
  { id: 2, author_id: 2, author_name: 'Sam', body: 'Paid my half', created_at: '2026-10-12T18:00:00+00:00' },
] };
const noop = () => {};
const one = (txn: Txn) => (
  <ReviewCard key={txn.id} txn={txn} chips={['shopping', 'subscriptions']} today={new Date(2026, 9, 13)} onBegin={() => 'e1'}
    onDone={noop} onFail={noop} onNote={noop} />
);
const byId = (id: number) => screen.getAllByTestId('review-card').find((c) => c.dataset.id === String(id))!;

describe('a Review card shows its notes, as the transaction page does', () => {
  it('two notes from two people, newest last, with Remove only on the signed-in person’s own', async () => {
    stubFetch({ '/api/auth/me': ME, '/api/reimburse/payers': { payers: [] }, '/api/transactions/7/notes': NOTES });
    wrapBook(one(TXN));
    const card = screen.getByTestId('review-card');
    await within(card).findByText('Sam, Oct 12:');
    const lines = within(card).getAllByRole('listitem');
    expect(lines.map((li) => li.textContent)).toEqual(['JR, Oct 11: Water heater, half paid by SamRemove', 'Sam, Oct 12: Paid my half']);
    expect(within(lines[0]).getByRole('button', { name: 'Remove note from Oct 11' })).toBeInTheDocument();
    expect(within(lines[1]).queryByRole('button')).toBeNull();
    expect(within(card).queryByText('Notes')).toBeNull();                 // lean: no heading on a card
  });

  it('a card with no notes asks for none and shows nothing new', async () => {
    const fetchMock = stubFetch({ '/api/auth/me': ME, '/api/reimburse/payers': { payers: [] }, '/api/transactions/8/notes': NOTES });
    wrapBook(<>{one({ ...TXN, note_count: 0 })}{one({ ...TXN, id: 8, note_count: 2 })}</>);
    await within(byId(8)).findByText('Sam, Oct 12:');                     // the card beside it has had its turn
    expect(callsTo(fetchMock, 'GET', '/api/transactions/7/notes')).toHaveLength(0);
    expect(byId(7).querySelector('.notes__list')).toBeNull();
    expect(within(byId(7)).queryByText('No notes yet.')).toBeNull();
  });

  it('in a parent book (no Note button) Remove puts focus on the card, not the page, and hands Review the Undo', async () => {
    const onNote = vi.fn();
    stubFetch({ '/api/auth/me': ME, '/api/reimburse/payers': { payers: [] }, '/api/transactions/7/notes': NOTES,
      'DELETE /api/transactions/7/notes/1': () => reply({ undo: 'tok-rm' }) });
    wrapBook(<ReviewCard txn={TXN} chips={['shopping']} today={new Date(2026, 9, 13)} onBegin={() => 'e1'} onDone={noop}
      onFail={noop} onNote={onNote} />, { kind: 'parent' });
    const card = screen.getByTestId('review-card');
    const b = await within(card).findByRole('button', { name: 'Remove note from Oct 11' });
    b.focus();
    fireEvent.click(b);
    expect(document.activeElement).toBe(card);
    await waitFor(() => expect(onNote).toHaveBeenCalledWith(TXN, 'tok-rm', 'Removed'));
  });

  it('a viewer reads the notes, with no Remove', async () => {
    stubFetch({ '/api/auth/me': ME, '/api/reimburse/payers': { payers: [] }, '/api/transactions/7/notes': NOTES });
    wrapBook(one(TXN), { role: 'viewer' });
    const card = screen.getByTestId('review-card');
    expect(await within(card).findByText('JR, Oct 11:')).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: /^Remove/ })).toBeNull();
  });
});
