import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, reply, stubFetch, wrapBook } from '../../test-utils';
import Export, { transactionsHref } from './Export';

afterEach(() => { vi.unstubAllGlobals(); });

const region = (name: string) => screen.getByRole('region', { name });

describe('Export', () => {
  it('builds the transactions link from the range and the notes box', () => {
    expect(transactionsHref('ours', 'all', '', '', false, 2026)).toBe('/api/b/ours/export/transactions.csv');
    expect(transactionsHref('ours', 'this', '', '', false, 2026)).toBe('/api/b/ours/export/transactions.csv?from=2026-01-01&to=2026-12-31');
    expect(transactionsHref('ours', 'last', '', '', true, 2026)).toBe('/api/b/ours/export/transactions.csv?from=2025-01-01&to=2025-12-31&notes=1');
    expect(transactionsHref('ours', 'choose', '2026-02-01', '2026-03-15', false, 2026))
      .toBe('/api/b/ours/export/transactions.csv?from=2026-02-01&to=2026-03-15');
  });

  it('downloads with a plain link, notes only when ticked, unticked again on return', async () => {
    stubFetch({ '/api/business': { type: 'none' } });
    const { unmount } = wrapBook(<Export go={() => {}} />);
    const tx = region('Transactions (CSV)');
    const link = within(tx).getByRole('link', { name: 'Download' });
    expect(link).toHaveAttribute('href', '/api/b/ours/export/transactions.csv');
    fireEvent.change(within(tx).getByLabelText('Range'), { target: { value: 'this' } });
    fireEvent.click(within(tx).getByRole('checkbox', { name: 'Include notes' }));
    expect(link).toHaveAttribute('href', '/api/b/ours/export/transactions.csv?from=2026-01-01&to=2026-12-31&notes=1');
    fireEvent.change(within(tx).getByLabelText('Range'), { target: { value: 'choose' } });
    fireEvent.change(within(tx).getByLabelText('From'), { target: { value: '2026-02-01' } });
    fireEvent.change(within(tx).getByLabelText('To'), { target: { value: '2026-03-15' } });
    expect(link).toHaveAttribute('href', '/api/b/ours/export/transactions.csv?from=2026-02-01&to=2026-03-15&notes=1');
    unmount();
    wrapBook(<Export go={() => {}} />);
    expect(within(region('Transactions (CSV)')).getByRole('checkbox', { name: 'Include notes' })).not.toBeChecked();
  });

  it('shows the business report only for a household with a business', async () => {
    stubFetch({ '/api/business': { type: 'sole_prop' } });
    const first = wrapBook(<Export go={() => {}} />);
    const biz = await screen.findByRole('region', { name: 'Business report (CSV)' });
    expect(within(biz).getByRole('link', { name: 'Download' })).toHaveAttribute('href', '/api/b/ours/export/business.csv?year=2026');
    first.unmount();
    vi.unstubAllGlobals();
    const fn = stubFetch({ '/api/business': { type: 'sole_prop' } });
    wrapBook(<Export go={() => {}} />, { slug: 'mom', kind: 'parent' });
    expect(screen.queryByRole('region', { name: 'Business report (CSV)' })).toBeNull();
    expect(callsTo(fn, 'GET', '/api/business')).toHaveLength(0);
  });

  it('asks for a passphrase twice, at least 12 characters, then goes to the one-time link', async () => {
    const go = vi.fn();
    const fn = stubFetch({ '/api/business': { type: 'none' },
      'POST /api/export/backup': () => reply({ token: 'tok', filename: 'steward-ours-2026-10-30.steward-backup', bytes: 9 }, 201) });
    wrapBook(<Export go={go} />);
    fireEvent.click(screen.getByRole('button', { name: 'Make one' }));
    const panel = screen.getByRole('group', { name: 'Choose a passphrase for this backup' });
    const first = within(panel).getByLabelText('Passphrase');
    expect(first).toHaveAttribute('type', 'password');
    expect(first).toHaveAttribute('autocomplete', 'new-password');
    expect(first).toHaveAccessibleDescription(/Only this passphrase opens the file\. Steward can't recover it if it's lost\./);
    fireEvent.change(first, { target: { value: 'eleven char' } });
    fireEvent.change(within(panel).getByLabelText('Type it again'), { target: { value: 'eleven char' } });
    fireEvent.click(within(panel).getByRole('button', { name: 'Download backup' }));
    expect(within(panel).getByText('Use at least 12 characters.')).toBeInTheDocument();
    fireEvent.change(first, { target: { value: 'twelve chars' } });
    fireEvent.click(within(panel).getByRole('button', { name: 'Download backup' }));
    expect(within(panel).getByText("The two don't match.")).toBeInTheDocument();
    expect(callsTo(fn, 'POST', '/api/export/backup')).toHaveLength(0);
    fireEvent.change(within(panel).getByLabelText('Type it again'), { target: { value: 'twelve chars' } });
    fireEvent.click(within(panel).getByRole('button', { name: 'Download backup' }));
    expect(screen.getByText('Making the backup…')).toBeInTheDocument();
    await waitFor(() => expect(go).toHaveBeenCalledWith('/api/b/ours/export/backup/tok'));
    expect(callsTo(fn, 'POST', '/api/export/backup')[0].body).toEqual({ passphrase: 'twelve chars', again: 'twelve chars' });
  });

  it('shows and hides the passphrase with one button', () => {
    stubFetch({ '/api/business': { type: 'none' } });
    wrapBook(<Export go={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'Make one' }));
    const show = screen.getByRole('button', { name: 'Show' });
    expect(show).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(show);
    expect(show).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Passphrase')).toHaveAttribute('type', 'text');
  });

  it('says so when another backup is being made', async () => {
    stubFetch({ '/api/business': { type: 'none' },
      'POST /api/export/backup': () => reply({ error: 'Another backup is being made. Try again in a minute.' }, 429) });
    wrapBook(<Export go={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'Make one' }));
    fireEvent.change(screen.getByLabelText('Passphrase'), { target: { value: 'twelve chars' } });
    fireEvent.change(screen.getByLabelText('Type it again'), { target: { value: 'twelve chars' } });
    fireEvent.click(screen.getByRole('button', { name: 'Download backup' }));
    expect(await screen.findByText('Another backup is being made. Try again in a minute.')).toBeInTheDocument();
  });
});
