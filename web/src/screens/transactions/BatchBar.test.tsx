import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, expectRemovalSaid, stubFetch, wrapBook } from '../../test-utils';
import BatchBar from './BatchBar';

afterEach(() => { vi.unstubAllGlobals(); });

const ONE = { id: 9, account_id: 1, account_name: 'Card', filename: 'Chase-checking-2024.csv', format: 'chase_checking',
  row_count: 1204, imported_at: '2026-10-31T18:00:00+00:00', imported_by: 1, rolled_back_at: null, rows_in: 1204, undoable: true };

describe('the file’s bar on Transactions', () => {
  it('names the file, offers its Undo with today’s sheet, and says when it’s done', async () => {
    const fn = stubFetch({ '/api/import/batches/9': ONE, 'POST /api/import/batches/9/rollback': { deleted: 1204 } });
    wrapBook(<BatchBar batchId={9} />);
    expect(await screen.findByText('From Chase-checking-2024.csv')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'All transactions' })).toHaveAttribute('href', '/b/ours/transactions');
    const undo = screen.getByRole('button', { name: 'Undo this import' });
    undo.focus();
    fireEvent.click(undo);
    const ask = screen.getByRole('dialog', { name: 'Undo the import of Chase-checking-2024.csv?' });
    expect(within(ask).getByText(/^Its 1,204 rows are removed from Steward for good/)).toBeInTheDocument();
    fireEvent.click(within(ask).getByRole('button', { name: 'Undo this import' }));
    await waitFor(() => expect(callsTo(fn, 'POST', '/api/import/batches/9/rollback')).toHaveLength(1));
    // THO-1: the Undo gives way to the line, and the line holds focus rather than <body>.
    await expectRemovalSaid('Import undone.', () => screen.getByText('Import undone.').closest('[aria-live]') as HTMLElement);
    expect(screen.queryByRole('button', { name: 'Undo this import' })).toBeNull();
  });

  it('a viewer, or a file already undone, gets no Undo', async () => {
    stubFetch({ '/api/import/batches/9': { ...ONE, undoable: false } });
    wrapBook(<BatchBar batchId={9} />, { role: 'viewer' });
    expect(await screen.findByText('From Chase-checking-2024.csv')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo this import' })).toBeNull();
  });
});
