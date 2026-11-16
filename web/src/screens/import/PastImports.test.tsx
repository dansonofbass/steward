import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, expectRemovalSaid, reply, stubFetch, wrap } from '../../test-utils';
import { PastImports } from './PastImports';

afterEach(() => { vi.unstubAllGlobals(); });

const file = (id: number, filename: string, rows: number, rolled: string | null = null) => ({
  id, account_id: 1, account_name: 'Amex Gold', filename, format: 'layout', row_count: rows,
  imported_at: '2026-10-12T18:00:00Z', imported_by: 1, rolled_back_at: rolled });
const GROUPS = { imports: [
  { set_id: 5, imported_at: '2026-10-12T18:00:00Z', imported_by: 1, rolled_back_at: null,
    files: [file(9, 'activity (3).csv', 1200), file(10, 'statement.qfx', 311)] },
  { set_id: null, imported_at: '2026-09-01T18:00:00Z', imported_by: 1, rolled_back_at: null, files: [file(3, 'october.csv', 400)] },
] };

describe('Past imports', () => {
  it('a batch reads as files, rows and its day, and expands to its files', async () => {
    stubFetch({ '/api/import/batches': GROUPS });
    wrap(<PastImports />);
    const batch = await screen.findByRole('button', { name: '2 files · 1,511 rows · Oct 12' });
    expect(batch).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(batch);
    expect(screen.getByText('activity (3).csv')).toBeInTheDocument();
    expect(screen.getByText('statement.qfx')).toBeInTheDocument();
  });

  it('Undo this import for a batch asks first, then undoes every file', async () => {
    const fn = stubFetch({ '/api/import/batches': GROUPS, 'POST /api/import/sets/5/rollback': () => reply({ deleted: 1511 }) });
    wrap(<PastImports />);
    const [first] = await screen.findAllByRole('button', { name: 'Undo this import' });
    fireEvent.click(first);
    const ask = screen.getByRole('dialog', { name: 'Undo the import of 2 files?' });
    expect(within(ask).getByText(/^Its 1,511 rows from 2 files are removed from Steward for good/)).toBeInTheDocument();
    expect(callsTo(fn, 'POST', '/api/import/sets')).toHaveLength(0);
    fireEvent.click(within(ask).getByRole('button', { name: 'Undo this import' }));
    await waitFor(() => expect(callsTo(fn, 'POST', '/api/import/sets/5/rollback')).toHaveLength(1));
  });

  it('after an undo, says so and keeps focus on Past imports, where the Undo was (THO-1)', async () => {
    let groups: { imports: { rolled_back_at: string | null }[] } = GROUPS;
    stubFetch({ '/api/import/batches': () => reply(groups), 'POST /api/import/sets/5/rollback': () => {
      groups = { imports: [{ ...GROUPS.imports[0], rolled_back_at: '2026-10-13T18:00:00Z' }, GROUPS.imports[1]] };
      return reply({ deleted: 1511 });
    } });
    wrap(<PastImports />);
    const [first] = await screen.findAllByRole('button', { name: 'Undo this import' });
    first.focus();
    fireEvent.click(first);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Undo this import' }));
    await expectRemovalSaid('Import undone.', () => screen.getByRole('heading', { name: 'Past imports' }));
    expect(screen.getAllByRole('button', { name: 'Undo this import' })).toHaveLength(1);
  });

  it('a file from before batches keeps today’s sheet', async () => {
    stubFetch({ '/api/import/batches': GROUPS });
    wrap(<PastImports />);
    const undos = await screen.findAllByRole('button', { name: 'Undo this import' });
    fireEvent.click(undos[1]);
    expect(screen.getByRole('dialog', { name: 'Undo the import of october.csv?' })).toBeInTheDocument();
  });

  it('a scanned statement reads like a statement, with its didn’t-add-up tag', async () => {
    const scan = { ...file(30, 'scan_0042.pdf', 18), format: 'pdf_scan', period_end: '2026-03-31', check_state: 'anyway' };
    stubFetch({ '/api/import/batches': { imports: [{ set_id: null, imported_at: '2026-10-12T18:00:00Z', imported_by: 1, rolled_back_at: null, files: [scan] }] } });
    wrap(<PastImports />);
    expect(await screen.findByText('Amex Gold · Mar 2026 (PDF) · 18 rows')).toBeInTheDocument();
    expect(screen.getByText("didn't add up")).toBeInTheDocument();
  });

  it('a statement reads as its month and says when it did not add up', async () => {
    const pdf = (id: number, anyway: boolean) => ({ ...file(id, `stmt${id}.pdf`, 24), format: 'pdf', period_end: '2026-03-31', check_state: anyway ? 'anyway' : 'adds_up' });
    stubFetch({ '/api/import/batches': { imports: [
      { set_id: null, imported_at: '2026-10-12T18:00:00Z', imported_by: 1, rolled_back_at: null, files: [pdf(20, false)] },
      { set_id: null, imported_at: '2026-10-12T18:00:00Z', imported_by: 1, rolled_back_at: null, files: [pdf(21, true)] }] } });
    wrap(<PastImports />);
    expect(await screen.findAllByText('Amex Gold · Mar 2026 (PDF) · 24 rows')).toHaveLength(2);
    expect(screen.getAllByText("didn't add up")).toHaveLength(1);
    expect(screen.queryByText('stmt20.pdf')).toBeNull();
  });
});
