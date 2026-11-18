import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setCurrentBook } from '../api/book';
import { useAccounts } from '../api/hooks';
import type { BookSummary } from '../api/types';
import { makeQueryClient } from '../queryClient';
import AccountPage from '../screens/accounts/AccountPage';
import { ACCTS } from '../screens/accounts/fixtures';
import { reply, stubFetch } from '../test-utils';
import { BookScope } from './BookScope';
import { ToBook } from './ToBook';
import { forgetProfileOpened } from './profileVisit';
import { noteWelcomeShown } from './welcomeVisit';

afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); sessionStorage.clear(); forgetProfileOpened(); setCurrentBook('ours'); });
const REVIEW = { uncategorized: [], count: 0, duplicates: [], duplicate_count: 0, top_categories: [], business: [], business_count: 0 };
const book = (slug: string, extra: Partial<BookSummary> = {}): BookSummary => ({
  slug, name: slug === 'ours' ? 'Ours' : 'Mom', kind: slug === 'ours' ? 'household' : 'parent', role: 'manager',
  available: true, reason: null, owners: [], profile: slug === 'ours' ? { seen: true, confirmed: true, later_until: null } : null, ...extra,
});
const me = (books: BookSummary[]) => ({ user: { id: 1, username: 'jr', display_name: 'JR' }, session: { id: 1, device_label: 'Phone', created_at: '2026-10-01T00:00:00Z' }, books });

function Names() {
  const a = useAccounts();
  return <p>{a.data ? a.data.accounts.map((x) => x.name).join(',') : 'loading'}</p>;
}
function mount(path: string | { pathname: string; state: unknown }, qc = makeQueryClient()) {
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/b/:slug" element={<BookScope />}><Route index element={<Names />} /><Route path="plan" element={<p>Plan</p>} />
            <Route path="spending" element={<p>Spending screen</p>} /><Route path="settings" element={<p>Settings screen</p>} />
            <Route path="profile" element={<p>Profile screen</p>} /><Route path="welcome" element={<p>Welcome screen</p>} /><Route path="transactions" element={<p>Transactions</p>} />
            <Route path="accounts/:id" element={<AccountPage />} /></Route>
          <Route path="/" element={<ToBook />} />
          <Route path="/transactions" element={<ToBook />} />
          <Route path="/accounts" element={<ToBook />} />
          <Route path="/b/:slug/accounts" element={<p>Accounts page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('BookScope', () => {
  it('fetches the book in the address and hides Plan in a parent book', async () => {
    const fetchMock = stubFetch({ '/api/auth/me': me([book('ours'), book('mom')]), '/api/review': REVIEW, '/api/accounts': { accounts: [{ name: 'Mom checking' }] } });
    mount('/b/mom');
    expect(await screen.findByText('Mom checking')).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([u]) => u === '/api/b/mom/accounts')).toBe(true);
    expect(screen.queryByRole('link', { name: 'Plan' })).toBeNull();
  });
  it('a person with one book sees no switcher and the household tabs', async () => {
    stubFetch({ '/api/auth/me': me([book('ours')]), '/api/review': REVIEW, '/api/accounts': { accounts: [] } });
    mount('/b/ours');
    expect(await screen.findByRole('link', { name: 'Plan' })).toHaveAttribute('href', '/b/ours/plan');
    expect(screen.queryByRole('button', { name: /Switch book/ })).toBeNull();
  });
  it('switching books never shows the other book\'s cached accounts', async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => { release = r; });
    stubFetch({
      '/api/auth/me': me([book('ours'), book('mom')]), '/api/review': REVIEW,
      '/api/accounts': async () => { await gate; return reply({ accounts: [{ name: 'Mom checking' }] }); },
    });
    const qc = makeQueryClient();
    setCurrentBook('ours');
    qc.setQueryData(['accounts'], { accounts: [{ name: 'Ours checking' }] });
    mount('/b/mom', qc);
    expect(await screen.findByText('loading')).toBeInTheDocument();
    expect(screen.queryByText('Ours checking')).toBeNull();
    release();
    expect(await screen.findByText('Mom checking')).toBeInTheDocument();
  });
  it('a household manager who hasn\'t seen Profile starts there, from the book\'s Home only', async () => {
    stubFetch({ '/api/auth/me': me([book('ours', { profile: { seen: false, confirmed: false, later_until: null } })]), '/api/review': REVIEW });
    mount('/b/ours');
    expect(await screen.findByText('Profile screen')).toBeInTheDocument();
  });
  it('opens Profile from Home at most once a session, and says why (issue 30)', async () => {
    stubFetch({ '/api/auth/me': me([book('ours', { profile: { seen: false, confirmed: false, later_until: null, finished: false } })]), '/api/review': REVIEW, '/api/accounts': { accounts: [] } });
    const first = mount('/b/ours');
    expect(await screen.findByText('Profile screen')).toBeInTheDocument();
    first.unmount();
    mount('/b/ours');
    expect(await screen.findByText('loading')).toBeInTheDocument();
    expect(screen.queryByText('Profile screen')).toBeNull();
  });
  it('never opens a finished profile from Home, seen or not (issue 30)', async () => {
    stubFetch({ '/api/auth/me': me([book('ours', { profile: { seen: false, confirmed: false, later_until: null, finished: true } })]), '/api/review': REVIEW, '/api/accounts': { accounts: [] } });
    mount('/b/ours');
    expect(await screen.findByText('loading')).toBeInTheDocument();
    expect(screen.queryByText('Profile screen')).toBeNull();
  });
  it('sends a household maker with an unmarked welcome to /welcome once this visit', async () => {
    stubFetch({ '/api/auth/me': me([book('maker', { kind: 'household', welcome: 'first_run' })]), '/api/review': REVIEW, '/api/accounts': { accounts: [] } });   // its own slug: the visit is remembered per page load
    const first = mount('/b/maker');
    expect(await screen.findByText('Welcome screen')).toBeInTheDocument();
    first.unmount();
    noteWelcomeShown('maker');
    mount('/b/maker');
    expect(await screen.findByText('loading')).toBeInTheDocument();
    expect(screen.queryByText('Welcome screen')).toBeNull();
  });
  it('sends a partner, a viewer too, the same way', async () => {
    stubFetch({ '/api/auth/me': me([book('mom', { welcome: 'partner', role: 'viewer' })]), '/api/review': REVIEW });
    mount('/b/mom');
    expect(await screen.findByText('Welcome screen')).toBeInTheDocument();
  });
  it("holds Profile's first visit while a welcome waits, and never sends a Sample to Profile", async () => {
    const unseen = { seen: false, confirmed: false, later_until: null };
    stubFetch({ '/api/auth/me': me([book('ours', { welcome: 'first_run', profile: unseen })]), '/api/review': REVIEW });
    const a = mount('/b/ours');
    expect(await screen.findByText('Welcome screen')).toBeInTheDocument();
    expect(screen.queryByText('Profile screen')).toBeNull();
    a.unmount();
    stubFetch({ '/api/auth/me': me([book('ours', { welcome: null, sample: true, profile: unseen })]), '/api/review': REVIEW, '/api/accounts': { accounts: [] } });
    mount('/b/ours');
    expect(await screen.findByText('loading')).toBeInTheDocument();
    expect(screen.queryByText('Profile screen')).toBeNull();
  });
  it('mounts the ribbon in a Sample only, on every screen', async () => {
    const sample = book('sample', { name: 'Sample household', kind: 'household', sample: true, profile: null });
    stubFetch({ '/api/auth/me': me([book('ours'), sample]), '/api/review': REVIEW, '/api/accounts': { accounts: [] } });
    for (const path of ['/b/sample', '/b/sample/spending', '/b/sample/settings']) {
      const m = mount(path);
      expect(await screen.findByRole('note')).toHaveTextContent('Sample');
      expect(screen.getByRole('link', { name: 'Your book' })).toHaveAttribute('href', '/b/ours');
      m.unmount();
    }
    mount('/b/ours');
    expect(await screen.findByText('loading')).toBeInTheDocument();
    expect(screen.queryByRole('note')).toBeNull();
  });
  it('shows the Sample-removed Undo when the router state says so', async () => {
    stubFetch({ '/api/auth/me': me([book('ours')]), '/api/review': REVIEW, '/api/accounts': { accounts: [] } });
    mount({ pathname: '/b/ours', state: { sampleRemoved: true } });
    expect(await screen.findByText('Sample removed')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument();
  });
  it('an unseen manager opening another screen stays there', async () => {
    stubFetch({ '/api/auth/me': me([book('ours', { profile: { seen: false, confirmed: false, later_until: null } })]), '/api/review': REVIEW });
    mount('/b/ours/transactions');
    expect(await screen.findByText('Transactions')).toBeInTheDocument();
    expect(screen.queryByText('Profile screen')).toBeNull();
  });
  it('a book that can\'t be opened says so, with the reason for managers', async () => {
    stubFetch({ '/api/auth/me': me([book('ours'), book('mom', { available: false, reason: "The book's file is missing." })]), '/api/review': REVIEW });
    mount('/b/mom');
    expect(await screen.findByText("This book can't be opened right now.")).toBeInTheDocument();
    expect(screen.getByText("The book's file is missing.")).toBeInTheDocument();
  });
  it('an old address goes to the last-used book, keeping the screen', async () => {
    localStorage.setItem('steward.lastBook', 'mom');
    stubFetch({ '/api/auth/me': me([book('ours'), book('mom')]), '/api/review': REVIEW });
    mount('/transactions');
    expect(await screen.findByText('Transactions')).toBeInTheDocument();
  });
  it('the old Accounts address goes to the last-used book', async () => {
    localStorage.setItem('steward.lastBook', 'mom');
    stubFetch({ '/api/auth/me': me([book('ours'), book('mom')]), '/api/review': REVIEW });
    mount('/accounts');
    expect(await screen.findByText('Accounts page')).toBeInTheDocument();
  });
  it('a person in no book is told so', async () => {
    const fetchMock = stubFetch({ '/api/auth/me': me([]) });
    mount('/');
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(await screen.findByText("You aren't in any book yet.")).toBeInTheDocument();
  });
  it('shows a viewer no Review count', async () => {
    const fetchMock = stubFetch({ '/api/auth/me': me([book('mom', { role: 'viewer' })]), '/api/review': { ...REVIEW, count: 4 }, '/api/accounts': { accounts: [] } });
    const { container } = mount('/b/mom');
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/review'))).toBe(true));
    await new Promise((r) => setTimeout(r, 0));
    expect(container.querySelector('.nav__count')).toBeNull();
  });

  it('counts business questions in the Review badge for managers', async () => {
    stubFetch({ '/api/auth/me': me([book('ours')]), '/api/review': { ...REVIEW, count: 2, business_count: 3 }, '/api/accounts': { accounts: [] } });
    const { container } = mount('/b/ours');
    await waitFor(() => expect(container.querySelector('.nav__count')?.textContent).toBe('5'));
  });

  it('shows the initials on every screen and no header Ask button', async () => {
    stubFetch({ '/api/auth/me': me([book('ours')]), '/api/review': REVIEW, '/api/accounts': { accounts: [] } });
    mount('/b/ours');
    // One in the phone's top bar and one at the foot of the laptop rail; the CSS shows one of them.
    expect(await screen.findAllByRole('button', { name: /^You: / })).toHaveLength(2);
    expect(screen.getByRole('link', { name: 'Ask' })).toHaveAttribute('href', '/b/ours/ask');   // the tab; Ask about this is a button on the pages that have one
    expect(document.querySelector('.ask-btn')).toBeNull();
  });
  it('an account page with chat on has the tab as its one Ask link and one Ask about button', async () => {
    const checking = { ...ACCTS[0], id: 12, name: 'Checking' };
    stubFetch({ '/api/auth/me': me([book('ours', { chat: true })]), '/api/review': REVIEW, '/api/accounts': { accounts: [checking] },
      '/api/transactions': { transactions: [], next_cursor: null } });
    mount('/b/ours/accounts/12');
    expect(await screen.findByRole('button', { name: 'Ask about Checking' })).toBeInTheDocument();
    const links = screen.getAllByRole('link', { name: 'Ask' });
    expect(links).toHaveLength(1);
    expect(links[0].closest('nav')).not.toBeNull();
  });
});
