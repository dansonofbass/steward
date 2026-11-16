import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, reply, stubFetch, wrapBook } from '../../test-utils';
import ThisBook from './ThisBook';

afterEach(() => vi.unstubAllGlobals());
const MOM = { slug: 'mom', name: 'Mom', kind: 'parent' as const, owners: [] };
const ME = { user: { id: 1, username: 'jr', display_name: 'JR' }, session: { id: 1, device_label: '', created_at: '' }, books: [] };

describe('Settings, This book', () => {
  it('a viewer reads the name, with nothing to change', () => {
    wrapBook(<ThisBook />, { ...MOM, role: 'viewer' }, '/b/mom/settings/book');
    expect(screen.getByRole('heading', { level: 2, name: 'This book' })).toBeInTheDocument();
    expect(screen.getByText('Mom')).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'Name' })).toBeNull();
  });

  it('a manager renames the book, and the new name is fetched again for the switcher', async () => {
    const fetchMock = stubFetch({ '/api/auth/me': ME, 'PATCH /api/books/mom': () => reply({ book: { ...MOM, name: 'Margaret' } }) });
    const { qc } = wrapBook(<ThisBook />, MOM, '/b/mom/settings/book');
    const refetch = vi.spyOn(qc, 'invalidateQueries');
    const name = screen.getByRole('textbox', { name: 'Name' });
    expect(name).toHaveValue('Mom');
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    fireEvent.change(name, { target: { value: ' Margaret ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Saved.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'PATCH', '/api/books/mom')[0].body).toEqual({ name: 'Margaret' });
    await waitFor(() => expect(refetch).toHaveBeenCalledWith({ queryKey: ['me'] }));
  });
});
