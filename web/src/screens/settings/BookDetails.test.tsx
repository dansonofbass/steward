import { screen, waitFor } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BookSummary } from '../../api/types';
import { renderAt, reply, stubFetch, wrapBook } from '../../test-utils';
import BookDetails from './BookDetails';

afterEach(() => vi.unstubAllGlobals());
const ours: BookSummary = { slug: 'ours', name: 'Ours', kind: 'household', role: 'manager', available: true, reason: null, owners: [], profile: null };
const mom: BookSummary = { ...ours, slug: 'mom', name: 'Mom', kind: 'parent' };
const me = (...books: BookSummary[]) => ({ user: { id: 1, username: 'jr', display_name: 'JR' }, session: { id: 1, device_label: '', created_at: '' }, books });

describe('Settings, Books, one book', () => {
  it("shows Mom's kind, managers and viewers, and Open Mom switches", async () => {
    stubFetch({ '/api/auth/me': me(ours, mom), '/api/books/mom/members': { members: [
      { user_id: 1, username: 'jr', display_name: 'JR', role: 'manager' }, { user_id: 3, username: 'dana', display_name: 'Dana', role: 'viewer' }] } });
    wrapBook(<BookDetails slug="mom" />, ours, '/b/ours/settings/books/mom');
    expect(await screen.findByText('Dana')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Mom' })).toBeInTheDocument();
    expect(screen.getByText('Parent')).toBeInTheDocument();
    expect(screen.getByText('JR')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Mom' })).toHaveAttribute('href', '/b/mom');
    expect(screen.getByRole('link', { name: 'Books' })).toHaveAttribute('href', '/b/ours/settings/books');
  });

  it('the book already open has no Open link, and an empty role says None; invitations are not people yet', async () => {
    stubFetch({ '/api/auth/me': me(ours, mom), '/api/books/ours/members': { members: [
      { user_id: 1, username: 'jr', display_name: 'JR', email: 'jr@example.com', role: 'manager' },
      { status: 'Invited', invite_id: '4', email: 'guest@example.com', role: 'viewer', user_id: null, username: null, display_name: null }] } });
    wrapBook(<BookDetails slug="ours" />, ours, '/b/ours/settings/books/ours');
    expect(await screen.findByText('JR')).toBeInTheDocument();
    expect(screen.getByText('None')).toBeInTheDocument();
    expect(screen.queryByText('guest@example.com')).toBeNull();
    expect(screen.queryByRole('link', { name: /^Open/ })).toBeNull();
  });

  it("shows the server's refusal when the members can't be read", async () => {
    stubFetch({ '/api/auth/me': me(ours, mom), '/api/books/mom/members': () => reply({ error: 'This book can\'t be opened right now.' }, 503) });
    wrapBook(<BookDetails slug="mom" />, ours, '/b/ours/settings/books/mom');
    expect(await screen.findByText("This book can't be opened right now.")).toBeInTheDocument();
    expect(screen.getByText('Parent')).toBeInTheDocument();
  });

  it("a book the person isn't in goes back to Books", async () => {
    stubFetch({});
    const { location } = renderAt(
      <Routes><Route path="/b/ours/settings/books/:step" element={<BookDetails slug="gone" />} /><Route path="*" element={null} /></Routes>,
      ours, '/settings/books/gone', [ours, mom],
    );
    await waitFor(() => expect(location.current.pathname).toBe('/b/ours/settings/books'));
  });
});
