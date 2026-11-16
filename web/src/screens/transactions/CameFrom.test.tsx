import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { stubFetch, wrapBook } from '../../test-utils';
import CameFrom, { cameFromLine } from './CameFrom';

afterEach(() => { vi.unstubAllGlobals(); });

describe('Came from', () => {
  it('reads one quiet line for each kind, in JR’s words', () => {
    expect(cameFromLine({ kind: 'simplefin', label: 'Chase', at: '2026-10-12T18:00:00+00:00' })).toBe('SimpleFIN · Chase · synced Oct 12');
    expect(cameFromLine({ kind: 'simplefin', label: 'Chase', at: null })).toBe('SimpleFIN · Chase');
    expect(cameFromLine({ kind: 'file', label: 'Chase-checking-2024.csv', at: '2026-10-31T18:00:00+00:00', batch_id: 9, by: 'JR', count: 1204, undoable: true }))
      .toBe('Chase-checking-2024.csv · imported Oct 31 by JR');
    expect(cameFromLine({ kind: 'file', label: 'october.csv', at: '2026-09-01T18:00:00+00:00', batch_id: 3, by: null, count: 1, undoable: false }))
      .toBe('october.csv · imported Sep 1');
    expect(cameFromLine({ kind: 'typed', label: null, at: null })).toBe('Typed in');
    expect(cameFromLine({ kind: 'statement', label: 'Statement_0324.pdf', at: '2026-10-31T18:00:00+00:00', batch_id: 88, by: 'JR', count: 42,
      undoable: true, period: { start: '2024-03-01', end: '2024-03-31' }, page: 2, check: 'adds_up', gap_cents: 0 }))
      .toBe('Statement, Mar 2024 (PDF), page 2 · imported Oct 31 · added up ✓');
    expect(cameFromLine({ kind: 'statement', label: 'Stmt_feb.pdf', at: '2026-10-31T18:00:00+00:00', batch_id: 89, by: null, count: 9,
      undoable: true, period: { start: '2024-02-01', end: '2024-02-29' }, page: null, check: 'anyway', gap_cents: 1240 }))
      .toBe("Statement, Feb 2024 (PDF) · imported Oct 31 · didn't add up by $12.40");
    expect(cameFromLine({ kind: 'statement', label: 'scan.pdf', at: '2026-10-31T18:00:00+00:00', batch_id: 90, by: null, count: 9,
      undoable: true, period: { start: '2024-02-01', end: '2024-02-29' }, page: null, check: 'anyway', gap_cents: null }))
      .toBe("Statement, Feb 2024 (PDF) · imported Oct 31 · didn't add up");
  });

  it('a statement’s line opens all its rows too', async () => {
    stubFetch({ '/api/transactions/9/came-from': { came_from: { kind: 'statement', label: 'Statement_0324.pdf',
      at: '2026-10-31T18:00:00+00:00', batch_id: 88, by: 'JR', count: 42, undoable: true, period: { start: '2024-03-01', end: '2024-03-31' },
      page: 2, check: 'adds_up', gap_cents: 0 } } });
    wrapBook(<CameFrom txnId={9} />);
    const link = await screen.findByRole('link', { name: 'Show all 42 from this file' });
    expect(link).toHaveAttribute('href', '/b/ours/transactions?batch=88&dates=all');
  });

  it('a file’s line opens all its rows', async () => {
    stubFetch({ '/api/transactions/7/came-from': { came_from: { kind: 'file', label: 'Chase-checking-2024.csv',
      at: '2026-10-31T18:00:00+00:00', batch_id: 9, by: 'JR', count: 1204, undoable: true } } });
    wrapBook(<CameFrom txnId={7} />);
    const link = await screen.findByRole('link', { name: 'Show all 1,204 from this file' });
    expect(link).toHaveAttribute('href', '/b/ours/transactions?batch=9&dates=all');
    expect(screen.getByTestId('came-from')).toHaveTextContent('Chase-checking-2024.csv · imported Oct 31 by JR · Show all 1,204 from this file');
  });

  it('a typed row has no link, and a failed load shows nothing', async () => {
    stubFetch({ '/api/transactions/8/came-from': { came_from: { kind: 'typed', label: null, at: null } } });
    wrapBook(<CameFrom txnId={8} />);
    expect(await screen.findByText('Typed in')).toBeInTheDocument();
    expect(screen.queryByRole('link')).toBeNull();
  });
});
