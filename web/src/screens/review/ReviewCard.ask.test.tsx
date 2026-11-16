import { fireEvent, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Txn } from '../../api/types';
import { askState, resetAsk } from '../../ask/store';
import { ME, stubFetch, wrapBook } from '../../test-utils';
import { ReviewCard } from './ReviewCard';

beforeEach(() => { localStorage.clear(); localStorage.setItem('steward-celebrations', 'off'); stubFetch({ '/api/reimburse/payers': { payers: [] } }); });
afterEach(() => { resetAsk(); vi.unstubAllGlobals(); });

const TXN: Txn = {
  id: 7, account_id: 1, account_name: 'Checking', posted_at: '2026-10-07', amount_cents: -1399,
  raw_description: 'PAYPAL *DISNEYPLUS', merchant: 'PayPal', category: 'uncategorized', is_business: false,
  is_transfer: false, business_pct: 0, business_line: null, business_source: 'none', category_source: 'none',
  reviewed_at: null, from_bank: true, matching: 0, reimburser_id: null, reimburse_ok: false, reason: 'p2p',
};
const card = (book = {}, more = {}) => wrapBook(
  <ReviewCard txn={TXN} chips={['shopping', 'subscriptions']} today={new Date(2026, 9, 13)} onBegin={() => 'e1'}
    onDone={() => {}} onFail={() => {}} onNote={() => {}} {...more} />, book);

describe("Ask on a Review card (P19)", () => {
  it('sits in the foot after Ignore and asks about the row by its id', () => {
    card({ chat: true });
    const ask = screen.getByRole('button', { name: 'Ask about PayPal' });
    expect(ask.closest('.rcard__actions')?.lastElementChild).toBe(ask);
    fireEvent.click(ask);
    expect(askState().about).toStrictEqual({ kind: 'transaction', id: 7 });
    expect(askState().surface).toStrictEqual({ kind: 'transaction', category: 'uncategorized' });
  });
  it('carries no note text, with the card’s notes on show', async () => {
    stubFetch({ '/api/auth/me': ME, '/api/reimburse/payers': { payers: [] }, '/api/transactions/7/notes': { notes: [
      { id: 1, author_id: 2, author_name: 'Sam', body: 'Plumber paid cash, ask Dana', created_at: '2026-10-12T18:00:00+00:00' }] } });
    card({ chat: true }, { txn: { ...TXN, note_count: 1 } });
    expect(await screen.findByText('Sam, Oct 12:')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Ask about PayPal' }));
    expect(askState().about).toStrictEqual({ kind: 'transaction', id: 7 });
    const { about, surface } = askState();
    expect(JSON.stringify({ about, surface })).not.toMatch(/Plumber|Dana|Sam/);
  });
  it('is hidden while picking for Select, and with chat off', () => {
    const picking = card({ chat: true }, { selecting: true });
    expect(document.querySelector('.ask-about')).toBeNull();
    picking.unmount();
    card();
    expect(document.querySelector('.ask-about')).toBeNull();
  });
});
