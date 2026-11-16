import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BOOK, callsTo, reply, stubFetch, wrapBook } from '../../../test-utils';
import { acct } from '../fixtures';
import { IMPORT_UNAVAILABLE } from './copy';
import { page } from './fixtures';
import Investment, { loadImport } from './Investment';
import PositionsImport from './PositionsImport';

afterEach(() => vi.unstubAllGlobals());

const GUESS = { symbol: 'Symbol', name: 'Description', shares: 'Quantity', value: 'Market Value', cost_basis: null };
const ASK = { needs_mapping: true, remembered: false, headers: ['Symbol', 'Description', 'Quantity', 'Market Value'], mapping: GUESS,
  sample: [['VTI', 'Vanguard Total Stock Market ETF', '400', '$108,000.00']], as_of: '2026-10-28' };
const READY = { ...ASK, needs_mapping: false, count: 2, total_cents: 15300000, skipped: 1, balance_cents: 15329000, balance_as_of: '2026-10-12',
  difference_cents: -29000, positions: [
    { symbol: 'VTI', name: 'Vanguard Total Stock Market ETF', shares_milli: 400000, value_cents: 10800000, cost_basis_cents: null },
    { symbol: 'VXUS', name: 'Vanguard Total International Stock ETF', shares_milli: 700000, value_cents: 4500000, cost_basis_cents: null }] };
const csv = () => new File(['Symbol,Description\n'], 'positions.csv', { type: 'text/csv' });
const formOf = (init: RequestInit) => init.body as FormData;
const taxable = acct({ id: 3, name: 'Taxable', type: 'brokerage_taxable', institution: 'Robo Invest' });

describe('Import positions (investment views spec, From a positions CSV)', () => {
  it('the first file confirms the guessed columns, checks the total against the balance, and saves', async () => {
    const onSaved = vi.fn();
    const fetchMock = stubFetch({
      'POST /api/accounts/3/positions/preview': (_u, init) => reply(formOf(init).get('mapping') ? READY : ASK),
      'POST /api/accounts/3/positions': () => reply({ count: 2, total_cents: 15300000, as_of: '2026-10-28', first: true }, 201),
    });
    wrapBook(<PositionsImport accountId={3} onClose={() => {}} onSaved={onSaved} />);
    fireEvent.change(screen.getByLabelText('Positions file (CSV)'), { target: { files: [csv()] } });
    expect(await screen.findByLabelText('Symbol')).toHaveValue('Symbol');
    expect(screen.getByLabelText('Value')).toHaveValue('Market Value');
    expect(screen.getByLabelText('Cost basis (optional)')).toHaveValue('');
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    expect(await screen.findByTestId('positions-preview')).toHaveTextContent('2 positions · $153,000; your balance is $153,290, a difference of $290.');
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ count: 2, total_cents: 15300000, as_of: '2026-10-28', first: true }));
    const saved = callsTo(fetchMock, 'POST', '/api/accounts/3/positions').filter((c) => !c.url.includes('preview'));
    const sent = formOf(saved[0].init);
    expect(JSON.parse(sent.get('mapping') as string)).toEqual(GUESS);
    expect(sent.get('file')).toBeInstanceOf(File);
    expect(sent.get('as_of')).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    // The browser's own date is never sent (pre-flight F8): the server's day is, and the preview never carried one.
    expect(sent.get('as_of')).toBe('2026-10-28');
    expect(callsTo(fetchMock, 'POST', '/api/accounts/3/positions/preview').every((c) => formOf(c.init).get('as_of') === null)).toBe(true);
  });

  it('sends a date only after the person changes it, and caps the input at the server\'s day', async () => {
    const fetchMock = stubFetch({
      'POST /api/accounts/3/positions/preview': { ...READY, remembered: true },
      'POST /api/accounts/3/positions': () => reply({ count: 2, total_cents: 15300000, as_of: '2026-10-20', first: false }, 201),
    });
    wrapBook(<PositionsImport accountId={3} onClose={() => {}} onSaved={() => {}} />);
    fireEvent.change(screen.getByLabelText('Positions file (CSV)'), { target: { files: [csv()] } });
    const date = await screen.findByLabelText('As of');
    expect(date).toHaveValue('2026-10-28');
    expect(date).toHaveAttribute('max', '2026-10-28');
    fireEvent.change(date, { target: { value: '2026-10-20' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/accounts/3/positions').filter((c) => !c.url.includes('preview'))).toHaveLength(1));
    const saved = callsTo(fetchMock, 'POST', '/api/accounts/3/positions').filter((c) => !c.url.includes('preview'));
    expect(formOf(saved[0].init).get('as_of')).toBe('2026-10-20');
  });

  it('keeps the first preview day as the date cap after a re-preview', async () => {
    let n = 0;
    stubFetch({ 'POST /api/accounts/3/positions/preview': () => reply({ ...READY, remembered: true, as_of: n++ === 0 ? '2026-10-28' : '2026-10-20' }) });
    wrapBook(<PositionsImport accountId={3} onClose={() => {}} onSaved={() => {}} />);
    fireEvent.change(screen.getByLabelText('Positions file (CSV)'), { target: { files: [csv()] } });
    expect(await screen.findByLabelText('As of')).toHaveAttribute('max', '2026-10-28');
    fireEvent.change(screen.getByLabelText('Positions file (CSV)'), { target: { files: [csv()] } });
    await waitFor(() => expect(n).toBe(2));
    expect(screen.getByLabelText('As of')).toHaveAttribute('max', '2026-10-28');
  });

  it('a remembered institution goes straight to the totals, with no columns to choose', async () => {
    stubFetch({ 'POST /api/accounts/3/positions/preview': { ...READY, remembered: true } });
    wrapBook(<PositionsImport accountId={3} onClose={() => {}} onSaved={() => {}} />);
    fireEvent.change(screen.getByLabelText('Positions file (CSV)'), { target: { files: [csv()] } });
    expect(await screen.findByTestId('positions-preview')).toBeInTheDocument();
    expect(screen.queryByLabelText('Symbol')).toBeNull();
    expect(screen.getByLabelText('As of')).toBeInTheDocument();
  });

  it("says why a file can't be read", async () => {
    stubFetch({ 'POST /api/accounts/3/positions/preview': () => reply({ error: 'No positions with a value were found in that file.' }, 422) });
    wrapBook(<PositionsImport accountId={3} onClose={() => {}} onSaved={() => {}} />);
    fireEvent.change(screen.getByLabelText('Positions file (CSV)'), { target: { files: [csv()] } });
    expect(await screen.findByText('No positions with a value were found in that file.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull();
  });

  it('opens from the page for a manager, and not for a viewer', async () => {
    stubFetch({ '/api/accounts/3/investment': page({ holdings: null, all_in: null }) });
    const { unmount } = wrapBook(<Investment account={taxable} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Import positions' }));
    expect(await screen.findByRole('dialog', { name: 'Import positions' })).toBeInTheDocument();
    unmount();
    wrapBook(<Investment account={taxable} />, { ...BOOK, role: 'viewer' });
    await screen.findByText(/^Import Robo Invest's positions/);
    expect(screen.queryByRole('button', { name: 'Import positions' })).toBeNull();
  });

  it("says so when the import's chunk can't be fetched", async () => {
    const { default: Missing } = await loadImport(() => Promise.reject(new Error('Failed to fetch dynamically imported module')));
    wrapBook(<Missing accountId={3} onClose={() => {}} onSaved={() => {}} />);
    expect(screen.getByText(IMPORT_UNAVAILABLE)).toBeInTheDocument();
  });
});
