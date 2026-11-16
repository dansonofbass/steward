import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Txn } from '../../../api/types';
import { useFakeTimers } from '../../../test-clock';
import { stubFetch, wrapBook } from '../../../test-utils';
import Review from '../../Review';

beforeEach(() => { localStorage.clear(); localStorage.setItem('steward-celebrations', 'off'); });
afterEach(() => { vi.useRealTimers(); });

const T = (id: number): Txn => ({
  id, account_id: 1, account_name: 'Rewards Card', posted_at: '2026-10-16', amount_cents: -8072, raw_description: `SHOP ${id}`,
  merchant: null, category: 'uncategorized', is_business: false, is_transfer: false, business_pct: 0, business_line: null,
  business_source: 'none', category_source: 'none', reviewed_at: null, from_bank: true, note_count: 0, reason: 'unsure',
  guess: 'groceries', matching: 0, reimburse_ok: false,
});
const Q = { uncategorized: [T(1), T(2), T(3)], count: 3, duplicates: [], duplicate_count: 0, top_categories: ['groceries', 'dining'], business: [], business_count: 0 };
const SORTED = (t: Txn) => ({ ...t, category: 'groceries', result: { category: 'groceries', applied: 0, ids: [], rule: 'made', undo: `tok-${t.id}` } });
const current = () => screen.getAllByTestId('focus-card').find((c) => c.dataset.role === 'current')!;
const media = (match: (q: string) => boolean) => vi.stubGlobal('matchMedia', (q: string) => ({ matches: match(q), media: q, addEventListener: () => {}, removeEventListener: () => {} }));
const phone = () => media((q) => q.includes('pointer: coarse'));

describe('the swipe demo and the hint (review focus P13)', () => {
  it('on a touch screen the nudge plays once, 500 ms after the first card shows, and not again', async () => {
    phone();
    useFakeTimers();
    stubFetch({ '/api/review': Q });
    const first = wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    act(() => { vi.advanceTimersByTime(499); });
    expect(current()).not.toHaveAttribute('data-demo');
    act(() => { vi.advanceTimersByTime(1); });
    expect(current()).toHaveAttribute('data-demo', 'playing');
    expect(localStorage.getItem('steward-swipe-demo')).toBe('nudged');
    act(() => { vi.advanceTimersByTime(1400); });
    expect(current()).not.toHaveAttribute('data-demo');
    expect(screen.getByTestId('focus-hint')).toHaveTextContent('Swipe or tap the buttons');
    first.unmount();
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    act(() => { vi.advanceTimersByTime(2000); });
    expect(current()).not.toHaveAttribute('data-demo');
    expect(screen.getByTestId('focus-hint')).toBeInTheDocument();       // until the first sort, across visits
  });

  it('a touch or a key cancels it', async () => {
    phone();
    useFakeTimers();
    stubFetch({ '/api/review': Q });
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    act(() => { vi.advanceTimersByTime(600); });
    expect(current()).toHaveAttribute('data-demo', 'playing');
    fireEvent.keyDown(document.body, { key: 'Shift' });
    expect(current()).not.toHaveAttribute('data-demo');
  });

  it('under reduced motion there is no nudge, but the hint shows; the first sort ends the hint for good', async () => {
    media((q) => q.includes('pointer: coarse') || q.includes('reduce'));
    stubFetch({ '/api/review': Q, 'PATCH /api/transactions/1': SORTED(T(1)) });
    wrapBook(<Review />);
    const bar = await screen.findByTestId('focus-bar');
    expect(screen.getByTestId('focus-hint')).toHaveTextContent('Swipe or tap the buttons');
    expect(current()).not.toHaveAttribute('data-demo');
    fireEvent.click(within(bar).getAllByRole('button')[1]);
    await waitFor(() => expect(current().dataset.id).toBe('2'));
    expect(screen.queryByTestId('focus-hint')).toBeNull();
    expect(localStorage.getItem('steward-swipe-demo')).toBe('done');
  });

  it('no nudge and no hint on a mouse, or with Swipe to sort off', async () => {
    useFakeTimers();
    stubFetch({ '/api/review': Q });
    const first = wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    act(() => { vi.advanceTimersByTime(2000); });
    expect(current()).not.toHaveAttribute('data-demo');
    expect(screen.queryByTestId('focus-hint')).toBeNull();
    first.unmount();
    phone();
    localStorage.setItem('steward-swipe', 'off');
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    act(() => { vi.advanceTimersByTime(2000); });
    expect(current()).not.toHaveAttribute('data-demo');
    expect(screen.queryByTestId('focus-hint')).toBeNull();
  });
});
