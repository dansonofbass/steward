import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { letTestingLibraryDriveFakeTimers, useFakeTimers } from '../../test-clock';
import { callsTo, reply, stubFetch, wrapBook } from '../../test-utils';
import { ACCT_CARD } from './fixtures';
import { Layouts } from './Layouts';

beforeEach(() => { useFakeTimers(); letTestingLibraryDriveFakeTimers(); });
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

const LAYOUT = { id: 4, label: 'First CU', header: ['Date', 'Description', 'Amount'], mapping: { date: 0, description: 1, amount: 2 },
  negate: true, date_format: '%m/%d/%Y', last_used_at: '2026-10-12T18:00:00+00:00', uses: 3, account_id: ACCT_CARD.id };

describe('Remembered layouts', () => {
  it('lists each layout with when it was last used, or says there are none', async () => {
    stubFetch({ '/api/accounts': { accounts: [ACCT_CARD] }, '/api/import/layouts': { layouts: [LAYOUT] } });
    wrapBook(<Layouts />);
    expect(await screen.findByText('First CU · last used Oct 12')).toBeInTheDocument();
    vi.unstubAllGlobals();
    stubFetch({ '/api/accounts': { accounts: [] }, '/api/import/layouts': { layouts: [] } });
    wrapBook(<Layouts />);
    expect(await screen.findByText('No layouts yet.')).toBeInTheDocument();
  });

  it('Edit opens the stored header with the sign and dates as choices and the name, and Save writes it', async () => {
    const fn = stubFetch({ '/api/accounts': { accounts: [ACCT_CARD] }, '/api/import/layouts': { layouts: [LAYOUT] },
      'PATCH /api/import/layouts/4': (_u, init) => reply({ layout: { ...LAYOUT, ...JSON.parse(String(init.body)) }, undo: 't' }) });
    wrapBook(<Layouts />);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    expect(screen.queryByRole('cell')).toBeNull();                             // no sample rows: files aren't kept
    expect((screen.getByLabelText('Column 3: Amount') as HTMLSelectElement).value).toBe('amount');
    expect(await screen.findByRole('radio', { name: 'Purchases are positive' })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'Month/day/year' })).toBeChecked();
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'First Credit Union' } });
    fireEvent.click(screen.getByRole('radio', { name: 'Day/month/year' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(callsTo(fn, 'PATCH', '/api/import/layouts/4')).toHaveLength(1));
    expect(callsTo(fn, 'PATCH', '/api/import/layouts/4')[0].body).toEqual({ label: 'First Credit Union',
      mapping: { date: 0, description: 1, amount: 2 }, negate: true, date_format: '%d/%m/%Y' });
  });

  it('Forget collapses the row and says so with Undo, through the journal', async () => {
    const fn = stubFetch({ '/api/accounts': { accounts: [ACCT_CARD] }, '/api/import/layouts': { layouts: [LAYOUT] },
      'DELETE /api/import/layouts/4': { undo: 'tok' }, 'POST /api/undo/tok': { undone: 0, transaction: null } });
    wrapBook(<Layouts />);
    fireEvent.click(await screen.findByRole('button', { name: 'Forget' }));
    expect(await screen.findByText('Forgot First CU')).toBeInTheDocument();
    fireEvent.click(within(screen.getByText('Forgot First CU').closest('[role=status]') as HTMLElement).getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(callsTo(fn, 'POST', '/api/undo/tok')).toHaveLength(1));
    expect(await screen.findByText('First CU · last used Oct 12')).toBeInTheDocument();   // Undo brings the row back
    act(() => { vi.advanceTimersByTime(10_000); });
  });

  it('a statement layout reads as one, has Forget only, and Forget takes the statement route with Undo', async () => {
    const STATEMENT = { id: 4, kind: 'statement', statement_kind: 'card', label: 'Summit Card Services', last_used_at: '2026-10-30T18:00:00+00:00', uses: 2, account_id: null };
    const fn = stubFetch({ '/api/accounts': { accounts: [ACCT_CARD] }, '/api/import/layouts': { layouts: [{ ...LAYOUT, kind: 'csv' }, STATEMENT] },
      'DELETE /api/import/statement-layouts/4': { undo: 'tok' }, 'POST /api/undo/tok': { undone: 0, transaction: null } });
    wrapBook(<Layouts />);
    const row = (await screen.findByText('Summit Card Services · statement · last used Oct 30')).closest('li') as HTMLElement;
    expect(within(row).queryByRole('button', { name: 'Edit' })).toBeNull();
    fireEvent.click(within(row).getByRole('button', { name: 'Forget' }));
    expect(await screen.findByText('Forgot Summit Card Services')).toBeInTheDocument();
    expect(callsTo(fn, 'DELETE', '/api/import/statement-layouts/4')).toHaveLength(1);
    expect(screen.getByText('First CU · last used Oct 12')).toBeInTheDocument();       // the CSV layout with the same id stays
    fireEvent.click(within(screen.getByText('Forgot Summit Card Services').closest('[role=status]') as HTMLElement).getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(callsTo(fn, 'POST', '/api/undo/tok')).toHaveLength(1));
    expect(await screen.findByText('Summit Card Services · statement · last used Oct 30')).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(10_000); });
  });
});
