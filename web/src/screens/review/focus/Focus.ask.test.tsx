import { fireEvent, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Txn } from '../../../api/types';
import { askState, resetAsk } from '../../../ask/store';
import { ME, stubFetch, wrapBook } from '../../../test-utils';
import Review from '../../Review';

beforeEach(() => { localStorage.clear(); localStorage.setItem('steward-celebrations', 'off'); });
afterEach(() => { resetAsk(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const T = (id: number, extra: Partial<Txn> = {}): Txn => ({
  id, account_id: 1, account_name: 'Rewards Card', posted_at: '2026-10-16', amount_cents: -8072, raw_description: `SHOP ${id}`,
  merchant: null, category: 'uncategorized', is_business: false, is_transfer: false, business_pct: 0, business_line: null,
  business_source: 'none', category_source: 'none', reviewed_at: null, from_bank: true, note_count: 0, reason: 'unknown',
  guess: null, matching: 0, reimburse_ok: false, ...extra,
});
const Q = { uncategorized: [T(1), T(2)], count: 2, duplicates: [], duplicate_count: 0, top_categories: ['groceries', 'dining'],
  business: [], business_count: 0 };
const current = () => screen.getAllByTestId('focus-card').find((c) => c.dataset.role === 'current')!;

describe('Ask about this in the focus card’s ⋯ menu (P19)', () => {
  it('asks about the current card by its id, with no key', async () => {
    stubFetch({ '/api/review': Q });
    wrapBook(<Review />, { chat: true });
    await screen.findByTestId('focus-bar');
    fireEvent.click(within(current()).getByRole('button', { name: 'More actions' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Ask about this' }));
    expect(askState().about).toStrictEqual({ kind: 'transaction', id: 1 });
    expect(askState().surface).toStrictEqual({ kind: 'transaction', category: 'uncategorized' });
  });
  it('carries no note text, with the card’s notes on show', async () => {
    stubFetch({ '/api/auth/me': ME, '/api/review': { ...Q, uncategorized: [T(1, { note_count: 1 }), T(2)] }, '/api/transactions/1/notes': { notes: [
      { id: 1, author_id: 2, author_name: 'Sam', body: 'Plumber paid cash, ask Dana', created_at: '2026-10-12T18:00:00+00:00' }] } });
    wrapBook(<Review />, { chat: true });
    await screen.findByTestId('focus-bar');
    expect(await within(current()).findByText(/Plumber paid cash/)).toBeInTheDocument();
    fireEvent.click(within(current()).getByRole('button', { name: 'More actions' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Ask about this' }));
    expect(askState().about).toStrictEqual({ kind: 'transaction', id: 1 });
    const { about, surface } = askState();
    expect(JSON.stringify({ about, surface })).not.toMatch(/Plumber|Dana|Sam/);
  });
  it('is not in the menu with chat off', async () => {
    stubFetch({ '/api/review': Q });
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    fireEvent.click(within(current()).getByRole('button', { name: 'More actions' }));
    expect(screen.queryByRole('menuitem', { name: 'Ask about this' })).toBeNull();
  });
});
