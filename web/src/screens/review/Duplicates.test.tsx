import { useQuery } from '@tanstack/react-query';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Txn } from '../../api/types';
import { api } from '../../api/client';
import { callsTo, expectRemovalSaid, reply, stubFetch, wrapBook } from '../../test-utils';
import { Duplicates } from './Duplicates';

afterEach(() => vi.unstubAllGlobals());
const txn = (over: Partial<Txn>): Txn => ({
  id: 1, posted_at: '2026-10-20', amount_cents: -4500, raw_description: 'COSTCO', merchant: 'Costco', category: 'groceries', account_id: 1,
  account_name: 'Checking', from_bank: true, ...over,
} as unknown as Txn);
const PAIR = { a: txn({ id: 1, from_bank: true }), b: txn({ id: 2, from_bank: false }) };

describe('Possible duplicates', () => {
  it('removing the file copy asks first and says the bank copy stays', async () => {
    const fetchMock = stubFetch({ 'DELETE /api/transactions/2': () => new Response(null, { status: 204 }) });
    const { qc } = wrapBook(<Duplicates pairs={[PAIR]} today={new Date('2026-10-25')} />);
    const spy = vi.spyOn(qc, 'invalidateQueries');
    expect(screen.getAllByRole('button', { name: 'Remove this one: COSTCO' })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Remove this one: COSTCO' }));
    const ask = screen.getByRole('dialog', { name: 'Remove this transaction?' });
    expect(within(ask).getByText("It came from a file, so it's gone from Steward for good. The bank's copy stays, and the log keeps a line saying it was removed.")).toBeInTheDocument();
    expect(callsTo(fetchMock, 'DELETE', '/api/transactions')).toHaveLength(0);
    fireEvent.click(within(ask).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/transactions/2')).toHaveLength(1));
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['spending'] }));   // Spending and Home's strip
  });
  it('when both sides came from a file, the sheet says the other copy stays, not a bank copy', async () => {
    const fetchMock = stubFetch({ 'DELETE /api/transactions/2': () => new Response(null, { status: 204 }) });
    wrapBook(<Duplicates pairs={[{ a: txn({ id: 1, from_bank: false }), b: txn({ id: 2, from_bank: false }) }]} today={new Date('2026-10-25')} />);
    expect(screen.getAllByRole('button', { name: 'Remove this one: COSTCO' })).toHaveLength(2);
    fireEvent.click(screen.getAllByRole('button', { name: 'Remove this one: COSTCO' })[1]);
    const ask = screen.getByRole('dialog', { name: 'Remove this transaction?' });
    expect(within(ask).getByText("It came from a file, so it's gone from Steward for good. The other copy stays, and the log keeps a line saying it was removed.")).toBeInTheDocument();
    expect(within(ask).queryByText(/bank's copy/)).toBeNull();
    fireEvent.click(within(ask).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/transactions/2')).toHaveLength(1));
  });
  it('after removing the last pair\'s copy, says which and the line holds focus, though the section is gone (THO-1)', async () => {
    let pairs = [PAIR];
    stubFetch({ '/api/review': () => reply({ pairs }), 'DELETE /api/transactions/2': () => { pairs = []; return new Response(null, { status: 204 }); } });
    // As Review does: the pairs come from the review query, which the removal refreshes.
    function Host() {
      const q = useQuery({ queryKey: ['review'], queryFn: () => api<{ pairs: typeof pairs }>('/api/review') });
      return q.data ? <Duplicates pairs={q.data.pairs} today={new Date('2026-10-25')} /> : null;
    }
    wrapBook(<Host />);
    const button = await screen.findByRole('button', { name: 'Remove this one: COSTCO' });
    button.focus();
    fireEvent.click(button);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
    await expectRemovalSaid('Removed COSTCO from Checking.', () => screen.getByText('Removed COSTCO from Checking.').closest('[aria-live]') as HTMLElement);
    expect(screen.queryByRole('heading', { name: 'Possible duplicates' })).toBeNull();
  });
});
