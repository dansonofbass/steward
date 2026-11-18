import { QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../../api/client';
import type { BookSummary, Me } from '../../api/types';
import { makeQueryClient } from '../../queryClient';
import { callsTo, reply, stubFetch } from '../../test-utils';
import { SampleRibbon, SampleUndo } from './Sample';

afterEach(() => { vi.unstubAllGlobals(); });

const ours: BookSummary = { slug: 'ours', name: 'Ours', kind: 'household', role: 'manager', available: true, reason: null, owners: [], profile: null, install: true };
const sample: BookSummary = { ...ours, slug: 'sample', name: 'Sample household', sample: true, install: false };
const meWith = (books: BookSummary[]): Me => ({ user: { id: 1, username: 'jr', display_name: 'JR', email: 'jr@example.com' }, books,
  session: { id: 1, device_label: 'Laptop', created_at: '2026-10-01T00:00:00Z' } });

function Where() {
  const l = useLocation();
  return <p data-testid="where">{l.pathname}|{JSON.stringify(l.state)}</p>;
}
function mount(ui: ReactElement,books: BookSummary[], path = '/b/sample') {
  const qc = makeQueryClient();
  qc.setQueryData(['me'], meWith(books));
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>{ui}<Routes><Route path="*" element={<Where />} /></Routes></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('the Sample ribbon', () => {
  it('names the Sample, opens the household book, and removes the Sample', async () => {
    const fetchMock = stubFetch({
      'DELETE /api/books/sample': { removed: true, household: 'ours' },
      '/api/auth/me': meWith([ours]),
    });
    const { container } = mount(<SampleRibbon />, [ours, sample]);
    expect(screen.getByText('Sample')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Your book' })).toHaveAttribute('href', '/b/ours');
    expect(container.querySelector('svg.acorn')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Remove the Sample' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/books/sample')).toHaveLength(1));
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/b/ours|{"sampleRemoved":true}'));
  });

  it("Your book opens the welcome while the household's first run waits", () => {
    mount(<SampleRibbon />, [{ ...ours, welcome: 'first_run' }, sample]);
    expect(screen.getByRole('link', { name: 'Your book' })).toHaveAttribute('href', '/b/ours/welcome');
  });
});

describe('the Sample Undo toast', () => {
  it('restores the Sample and opens it', async () => {
    const fetchMock = stubFetch({
      'POST /api/books/sample/restore': { book: sample },
      '/api/auth/me': meWith([ours, sample]),
    });
    mount(<SampleUndo />, [ours], '/b/ours');
    expect(screen.getByText('Sample removed')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/books/sample/restore')).toHaveLength(1));
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/b/sample'));
  });

  // The flaky e2e "Remove, Undo, Remove" (phone): Remove refetches /me, and that request, asked before the restore, could
  // still be on its way when Undo asked for a fresh one. The fresh one joined it, so the book list came back without
  // the Sample, and BookScope sent /b/sample back to /b/ours. Undo now drops a /me already on its way and asks anew.
  it('opens the restored Sample even while a /me asked before the restore is still on its way', async () => {
    let stale: (r: Response) => void = () => {};
    let asked = 0;
    const fetchMock = stubFetch({
      'POST /api/books/sample/restore': { book: sample },
      '/api/auth/me': () => (++asked === 1 ? new Promise<Response>((r) => { stale = r; }) : reply(meWith([ours, sample]))),
    });
    const qc = makeQueryClient();
    qc.setQueryData(['me'], meWith([ours]));
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/b/ours']}><SampleUndo /><Routes><Route path="*" element={<Where />} /></Routes></MemoryRouter>
      </QueryClientProvider>,
    );
    let removeAsk: Promise<Me> | undefined;                     // Remove's refetch, on its way
    void qc.fetchQuery({ queryKey: ['me'], queryFn: () => (removeAsk = api<Me>('/api/auth/me')), staleTime: 0 }).catch(() => {});
    await waitFor(() => expect(asked).toBe(1));
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/books/sample/restore')).toHaveLength(1));
    await waitFor(() => expect(asked).toBe(2));               // asked anew, after the restore
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/b/sample'));
    // The old answer lands late, and changes nothing. Wait for Remove's own query function to finish with it: React
    // Query's handler on that promise was attached first, so any cache write it makes has happened by then.
    stale(reply(meWith([ours])));
    await act(async () => { await removeAsk?.catch(() => {}); });
    expect(qc.getQueryData<Me>(['me'])?.books.map((b) => b.slug)).toEqual(['ours', 'sample']);
  });

  it('an Undo the server refuses says its words', async () => {
    const words = 'That sample is gone. You can make a new one from the welcome.';
    stubFetch({ 'POST /api/books/sample/restore': () => reply({ error: words }, 404) });
    mount(<SampleUndo />, [ours], '/b/ours');
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(await screen.findByText(words)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull();
  });
});
