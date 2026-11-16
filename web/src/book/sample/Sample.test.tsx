import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
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

  it('an Undo the server refuses says its words', async () => {
    const words = 'That sample is gone. You can make a new one from the welcome.';
    stubFetch({ 'POST /api/books/sample/restore': () => reply({ error: words }, 404) });
    mount(<SampleUndo />, [ours], '/b/ours');
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(await screen.findByText(words)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull();
  });
});
