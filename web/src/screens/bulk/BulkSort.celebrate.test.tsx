import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { REDUCE, withCelebrate } from '../../lib/celebrations';
import { useFakeTimers } from '../../test-clock';
import { stubFetch, wrapBook } from '../../test-utils';
import BulkSort from './BulkSort';

const fx = vi.hoisted(() => ({ sorted: vi.fn((_c: { card: HTMLElement; category: string; applied: number }) => () => {}),
  acorn: vi.fn(() => () => {}), winMoment: vi.fn(() => () => {}) }));
vi.mock('../../celebrate/celebrate', () => fx);

const SORT = { 'POST /api/transactions/sort': { sorted: 12, ids: Array.from({ length: 12 }, (_, i) => i + 1), category: 'transfer', skipped: [], undo: 'tok' } };
const sortTransfer = () => {
  fireEvent.click(screen.getByRole('button', { name: 'Sort as…' }));
  fireEvent.change(within(screen.getByRole('dialog', { name: 'Sort as…' })).getByRole('combobox'), { target: { value: 'transf' } });
  fireEvent.click(screen.getByRole('option', { name: 'Transfer' }));
};
const bar = () => <BulkSort selecting ids={Array.from({ length: 12 }, (_, i) => i + 1)} onCancel={() => {}} onSorted={() => {}} onUndone={() => {}} />;

// The celebrate chunk loads before the first test, so a celebration lands a microtask after it starts, never after a
// dynamic import, and each test runs on the fake clock, so a wait's ceiling is fake time, not the machine's load.
beforeAll(async () => { expect(await withCelebrate(() => true)).toBe(true); });
beforeEach(() => { useFakeTimers(); localStorage.clear(); fx.sorted.mockClear(); });
afterEach(() => { vi.unstubAllGlobals(); });

describe('a bulk sort celebrates once', () => {
  it('plays the category moment and the stamp once, on the result line, not once per row', async () => {
    stubFetch(SORT);
    wrapBook(bar());
    sortTransfer();
    const line = await screen.findByTestId('bulk-said');
    expect(line).toHaveTextContent('Sorted 12 as Transfer');
    await waitFor(() => expect(fx.sorted).toHaveBeenCalledTimes(1));
    expect(fx.sorted).toHaveBeenCalledWith(expect.objectContaining({ card: line, category: 'transfer', applied: 0 }));
  });

  it('plays nothing with Celebrations off, or under reduced motion', async () => {
    stubFetch(SORT);
    localStorage.setItem('steward-celebrations', 'off');
    const first = wrapBook(bar());
    sortTransfer();
    expect(await screen.findByTestId('bulk-said')).toHaveTextContent('Sorted 12 as Transfer');
    first.unmount();
    localStorage.clear();
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q === REDUCE, addEventListener() {}, removeEventListener() {} }));
    const second = wrapBook(bar());
    sortTransfer();
    expect(await screen.findByTestId('bulk-said')).toHaveTextContent('Sorted 12 as Transfer');
    second.unmount();
    // Then one with both on: once its moment has played, any the two above had started would have played first.
    vi.unstubAllGlobals();
    stubFetch(SORT);
    wrapBook(bar());
    sortTransfer();
    const line = await screen.findByTestId('bulk-said');
    await waitFor(() => expect(fx.sorted).toHaveBeenCalledTimes(1));
    expect(fx.sorted).toHaveBeenCalledWith(expect.objectContaining({ card: line }));
  });
});
