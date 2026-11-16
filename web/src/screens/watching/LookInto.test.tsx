import { fireEvent, screen, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BookSummary } from '../../api/types';
import { callsTo, reply, stubFetch, wrapBook } from '../../test-utils';
import { DONE_LIST, LIST, PARENT } from './fixtures';
import { LookInto } from './LookInto';

afterEach(() => vi.unstubAllGlobals());
const page = (path = '/b/margaret-ellis/look-into', book: Partial<BookSummary> = PARENT) =>
  wrapBook(<Routes><Route path="/b/:slug/look-into" element={<LookInto />} /></Routes>, book, path);

describe('Look into', () => {
  it('groups urgent first, with the filters and when the checks ran', async () => {
    stubFetch({ '/api/flags': LIST });
    page();
    expect(await screen.findByRole('heading', { name: 'Look into' })).toBeInTheDocument();
    expect(await screen.findByText("What the checks found in Margaret's accounts, urgent first. The checks ran today at 6:12 AM, after the bank feed sync.")).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Watching settings/ })).toHaveAttribute('href', '/b/margaret-ellis/settings/watching');
    expect(screen.getByRole('link', { name: /Home/ })).toHaveAttribute('href', '/b/margaret-ellis');
    const show = screen.getByRole('group', { name: 'Show' });
    expect(within(show).getByRole('button', { name: /To look into 6/ })).toHaveAttribute('aria-pressed', 'true');
    expect(within(show).getByRole('button', { name: /Done 3/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'All checks (6)' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Scam pattern (1)' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Way2Save savings' })).toBeInTheDocument();
    expect(screen.getByText('Urgent · 3')).toBeInTheDocument();
    expect(screen.getByText('Other · 3')).toBeInTheDocument();
    expect(screen.getAllByTestId('flag-row')).toHaveLength(6);
  });
  it('filters by check and shows Done with Show older', async () => {
    const fetchMock = stubFetch({
      '/api/flags?show=open&check=duplicate': { ...LIST, flags: LIST.flags.filter((f) => f.check === 'duplicate') },
      '/api/flags?show=done&offset=50': () => reply({ ...DONE_LIST, next_offset: null }),
      '/api/flags?show=done': { ...DONE_LIST, next_offset: 50 },
      '/api/flags': LIST,
    });
    page();
    await screen.findByRole('option', { name: 'Duplicate (1)' });
    fireEvent.change(screen.getByLabelText('Check'), { target: { value: 'duplicate' } });
    await vi.waitFor(() => expect(screen.getAllByTestId('flag-row')).toHaveLength(1));
    fireEvent.click(screen.getByRole('button', { name: /Done 3/ }));
    expect(await screen.findByText("Margaret's crown. Margaret told me about it on Sunday.", { exact: false })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Show older' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'GET', '/api/flags?show=done&offset=50')).toHaveLength(1));
  });
  it('says when nothing is open', async () => {
    stubFetch({ '/api/flags': { ...LIST, flags: [], counts: { open: 0, done: 3 }, checks: [] } });
    page();
    expect(await screen.findByText('Nothing to look into.')).toBeInTheDocument();
    expect(screen.getByText('The checks ran today at 6:12 AM over 14 new transactions in 3 accounts.')).toBeInTheDocument();
  });
  it('a viewer reads it under the read-only line', async () => {
    stubFetch({ '/api/flags': { ...LIST, can_edit: false, mail_ready: null } });
    page('/b/margaret-ellis/look-into', { ...PARENT, role: 'viewer' });
    expect(await screen.findByText('You can see this book but not change it.')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Watching settings/ })).toBeNull();
  });
});
