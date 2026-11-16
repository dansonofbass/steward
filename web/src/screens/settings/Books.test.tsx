import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BookSummary } from '../../api/types';
import { callsTo, renderAt, reply, stubFetch, wrapBook } from '../../test-utils';
import { AddBookSheet } from './AddBookSheet';
import Books from './Books';

afterEach(() => vi.unstubAllGlobals());
const ours: BookSummary = { slug: 'ours', name: 'Ours', kind: 'household', role: 'manager', available: true, reason: null, owners: [], profile: null };
const mom: BookSummary = { ...ours, slug: 'mom', name: 'Mom', kind: 'parent' };
const viewerOf = (b: BookSummary): BookSummary => ({ ...b, role: 'viewer' });
const me = (...books: BookSummary[]) => ({ user: { id: 1, username: 'jr', display_name: 'JR' }, session: { id: 1, device_label: '', created_at: '' }, books });
const ME = me(ours);

describe('Settings, Books', () => {
  it('adds a parent book with its owner names and opens its Members', async () => {
    const fetchMock = stubFetch({
      '/api/auth/me': ME,
      'POST /api/books': () => reply({ book: { ...ours, slug: 'mom-robins', name: "Mom (Robin's)", kind: 'parent' } }, 201),
    });
    wrapBook(<Routes><Route path="/b/ours" element={<Books />} /><Route path="/b/mom-robins/settings/members" element={<p>Members of mom</p>} /></Routes>);
    expect(await screen.findByText('This book · Household · you manage')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Add a book' }));
    const sheet = screen.getByRole('dialog', { name: 'Add a book' });
    fireEvent.change(within(sheet).getByLabelText('Name'), { target: { value: "Mom (Robin's)" } });
    expect(within(sheet).queryAllByRole('radio')).toHaveLength(0);
    fireEvent.change(within(sheet).getByLabelText('Owner names 1'), { target: { value: 'Margaret' } });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Add a name' }));
    fireEvent.change(within(sheet).getByLabelText('Owner names 3'), { target: { value: 'Robert (husband)' } });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Add book' }));
    expect(await screen.findByText('Members of mom')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/books')[0].body).toEqual({ name: "Mom (Robin's)", kind: 'parent', owner_names: ['Margaret', 'Joint', 'Robert (husband)'] });
  });
  it('AddBookSheet with onAdded stays where it is', async () => {
    const added = vi.fn();
    const onClose = vi.fn();
    stubFetch({ '/api/auth/me': ME, 'POST /api/books': () => reply({ book: { ...mom, name: 'Mom' } }, 201) });
    const { location } = renderAt(<AddBookSheet onClose={onClose} onAdded={added} />, ours, '/b/ours/welcome');
    const sheet = screen.getByRole('dialog', { name: 'Add a book' });
    fireEvent.change(within(sheet).getByLabelText('Name'), { target: { value: 'Mom' } });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Add book' }));
    await waitFor(() => expect(added).toHaveBeenCalledWith(expect.objectContaining({ slug: 'mom', name: 'Mom' })));
    expect(location.current.pathname).toBe('/b/ours/welcome');
  });
  it('offers no kind choice and shows the server\'s refusal', async () => {
    stubFetch({ '/api/auth/me': ME, 'POST /api/books': () => reply({ error: 'Enter a book name of up to 60 characters.' }, 422) });
    wrapBook(<Books />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add a book' }));
    const sheet = screen.getByRole('dialog', { name: 'Add a book' });
    expect(within(sheet).queryByText(/Household/)).toBeNull();
    expect(within(sheet).getByLabelText('Owner names 1')).toBeInTheDocument();
    fireEvent.click(within(sheet).getByRole('button', { name: 'Add book' }));
    await waitFor(() => expect(within(sheet).getByText('Enter a book name of up to 60 characters.')).toBeInTheDocument());
  });
  it('opening a book shows its details without switching (decision 10)', async () => {
    stubFetch({ '/api/auth/me': me(ours, mom) });
    wrapBook(<Books />, ours, '/b/ours/settings/books');
    expect(await screen.findByRole('link', { name: /^Ours/ })).toHaveAttribute('href', '/b/ours/settings/books/ours');
    expect(screen.getByRole('link', { name: /^Mom/ })).toHaveAttribute('href', '/b/ours/settings/books/mom');
    expect(screen.getByText('This book · Household · you manage')).toBeInTheDocument();
    expect(screen.getByText('Parent · you manage')).toBeInTheDocument();
  });
  it('Add a book is for managers only', async () => {
    stubFetch({ '/api/auth/me': me(viewerOf(ours), viewerOf(mom)) });
    wrapBook(<Books />, viewerOf(ours), '/b/ours/settings/books');
    await screen.findByRole('link', { name: /^Ours/ });
    expect(screen.getByText('This book · Household · you view')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add a book' })).toBeNull();
  });
  it('Add a book shows to someone who manages another book while only viewing this one', async () => {
    stubFetch({ '/api/auth/me': me(viewerOf(ours), mom) });
    wrapBook(<Books />, viewerOf(ours), '/b/ours/settings/books');
    expect(await screen.findByRole('button', { name: 'Add a book' })).toBeInTheDocument();
  });
});
