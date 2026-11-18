import { QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setCurrentBook } from './api/book';
import type { BookSummary } from './api/types';
import { makeQueryClient } from './queryClient';
import { routes } from './routes';
import { TARGETS } from './screens/spending/fixtures';
import { ACCTS } from './screens/accounts/fixtures';
import { GIFT_PAGE, PARENT } from './screens/watching/fixtures';
import { reply, stubFetch } from './test-utils';

afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); setCurrentBook('ours'); });
const book = (slug: string, name: string): BookSummary => ({
  slug, name, kind: 'household', role: 'manager', available: true, reason: null, owners: [],
  profile: { seen: true, confirmed: true, later_until: null },
});
const ME = { user: { id: 1, username: 'jr', display_name: 'JR' }, session: { id: 1, device_label: 'Phone', created_at: '2026-10-01T00:00:00Z' },
  books: [book('ours', 'Ours'), book('lake', 'Lake house')] };

/** The app's own route list, at an address from before books, with "lake" the last book used on this device. */
function open(path: string) {
  localStorage.setItem('steward.lastBook', 'lake');
  stubFetch({ '/api/auth/me': ME });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<QueryClientProvider client={makeQueryClient()}><RouterProvider router={router} /></QueryClientProvider>);
  return router;
}

describe('addresses without a book', () => {
  // Phase 10's new screens are bookmarkable too, so each is in the list that goes to the last-used book.
  it.each([
    ['/taxes', '/b/lake/taxes'],
    ['/plan/try', '/b/lake/plan/try'],
    ['/plan/how', '/b/lake/plan/how'],
    ['/profile', '/b/lake/profile'],
    ['/profile/kids/cover', '/b/lake/profile/kids/cover'],
    ['/you/devices', '/b/lake/you/devices'],
    ['/you/appearance', '/b/lake/you/appearance'],
    ['/you/help', '/b/lake/you/help'],
    ['/accounts', '/b/lake/accounts'],
    ['/accounts/7', '/b/lake/accounts/7'],
    ['/ask', '/b/lake/ask'],
    ['/ask/history', '/b/lake/ask/history'],
  ])('%s lands in the last-used book', async (from, to) => {
    const router = open(`${from}?from=bookmark`);
    await waitFor(() => expect(router.state.location.pathname).toBe(to));
    expect(router.state.location.search).toBe('?from=bookmark');
  });
});

describe('Set up Steward and Settings > Profile are Profile (P2)', () => {
  it.each([
    ['/b/ours/setup', '/b/ours/profile'],
    ['/b/ours/setup/pay?from=plan', '/b/ours/profile/you?from=plan'],
    ['/b/ours/setup/health', '/b/ours/profile/benefits'],
    ['/b/ours/settings/profile/children', '/b/ours/profile/kids'],
    ['/b/ours/settings/setup/home?from=bookmark', '/b/ours/profile/home?from=bookmark'],
  ])('%s goes to %s', async (from, to) => {
    const router = open(from);
    await waitFor(() => expect(`${router.state.location.pathname}${router.state.location.search}`).toBe(to));
  });
});

describe('Cash flow became Spending (decision 2)', () => {
  it.each([
    ['/b/ours/cashflow?month=2026-09', '/b/ours/spending'],
    ['/cashflow?month=2026-09', '/b/lake/spending'],
    ['/spending?month=2026-09', '/b/lake/spending'],
  ])('%s goes to %s and keeps the month', async (from, to) => {
    const router = open(from);
    await waitFor(() => expect(router.state.location.pathname).toBe(to));
    expect(router.state.location.search).toBe('?month=2026-09');
  });
});

describe('Set targets has its own address', () => {
  it('/spending/targets is Set targets, not a category called "targets"', async () => {
    stubFetch({ '/api/auth/me': ME, '/api/spending/targets': TARGETS });
    const router = createMemoryRouter(routes, { initialEntries: ['/b/ours/spending/targets'] });
    render(<QueryClientProvider client={makeQueryClient()}><RouterProvider router={router} /></QueryClientProvider>);
    expect(await screen.findByRole('heading', { level: 1, name: 'Set targets' })).toBeInTheDocument();
    expect(await screen.findByTestId('sumcard')).toBeInTheDocument();
    expect(screen.queryByText('That is not a category Spending tracks.')).toBeNull();
  });
});

describe("a page for one item is titled by its name (issue #29)", () => {
  it("an account's page takes the account's name once it has loaded, and the fixed noun before", async () => {
    let answer: (v: Response) => void = () => {};
    const accounts = new Promise<Response>((r) => { answer = r; });
    stubFetch({ '/api/auth/me': ME, '/api/accounts': () => accounts, '/api/transactions': { transactions: [], next_cursor: null } });
    const router = createMemoryRouter(routes, { initialEntries: ['/b/ours/accounts/1'] });
    render(<QueryClientProvider client={makeQueryClient()}><RouterProvider router={router} /></QueryClientProvider>);
    await waitFor(() => expect(document.title).toBe('Account · Steward'));
    answer(reply({ accounts: ACCTS }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Checking ••6789' })).toBeInTheDocument();
    // Privacy ruling: the title goes into the browser's history and sync, so it names the account without its number.
    await waitFor(() => expect(document.title).toBe('Checking · Steward'));
  });

  it("a flag's page keeps the fixed noun: a flag's title describes a money worry", async () => {
    const parentBook: BookSummary = { ...book(PARENT.slug, PARENT.name), kind: 'parent', owners: PARENT.owners };
    stubFetch({ '/api/auth/me': { ...ME, books: [...ME.books, parentBook] }, '/api/flags/41': GIFT_PAGE });
    const router = createMemoryRouter(routes, { initialEntries: [`/b/${PARENT.slug}/look-into/41`] });
    render(<QueryClientProvider client={makeQueryClient()}><RouterProvider router={router} /></QueryClientProvider>);
    expect(await screen.findByRole('heading', { level: 1, name: GIFT_PAGE.title })).toBeInTheDocument();
    // The flag has loaded and its page has rendered; flushing React's pending work leaves the title on the noun.
    await act(async () => {});
    expect(document.title).toBe('Something to look into · Steward');
  });
});

describe('the first-run page (release spec, section 6; guided setup spec 1.3)', () => {
  it('/setup opens without signing in', async () => {
    const f = stubFetch({ 'POST /api/setup/check': { ok: true } });
    const router = createMemoryRouter(routes, { initialEntries: [`/setup#${'A'.repeat(43)}`] });
    render(<QueryClientProvider client={makeQueryClient()}><RouterProvider router={router} /></QueryClientProvider>);
    expect(await screen.findByRole('heading', { name: 'Set up Steward' })).toBeInTheDocument();
    expect(f.mock.calls.some(([url]) => String(url).startsWith('/api/auth/me'))).toBe(false);
  });
  it('an old /setup/{step} address from before books goes Home', async () => {
    const router = open('/setup/pay');
    await waitFor(() => expect(router.state.location.pathname).toBe('/b/lake'));
  });
});
