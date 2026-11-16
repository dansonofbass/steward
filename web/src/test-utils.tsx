// Unit-test helpers only; nothing in the app imports this file.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter, useLocation, type Location } from 'react-router-dom';
import { expect, vi } from 'vitest';
import type { BookSummary, Me } from './api/types';
import { BookCtx, bookHref } from './book/BookContext';

export type Handler = (url: string, init: RequestInit) => Response | Promise<Response>;
export type Route = Handler | Record<string, unknown> | unknown[] | string | number | boolean | null;

export const reply = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

/** Stubs are written as screens write paths ('/api/accounts'); the client sends '/api/b/<book>/accounts'. */
export const unbook = (url: string) => url.replace(/^\/api\/b\/[^/]+\//, '/api/');

/** After a confirmed removal (THO-1): the line is said in a live region, and focus sits on `focus`, which is still in
 *  the page (not on <body>, where it falls when it goes back to the gone row's button). */
export async function expectRemovalSaid(line: string, focus: () => HTMLElement) {
  const said = await screen.findByText(line);
  expect(said.closest('[aria-live="polite"]')).not.toBeNull();
  await waitFor(() => expect(focus()).toHaveFocus());
  expect(document.body.contains(document.activeElement)).toBe(true);
  expect(document.activeElement).not.toBe(document.body);
}

/** Stubs fetch. Keys are "METHOD /path" or "/path" (GET); the longest matching prefix wins. */
export function stubFetch(routes: Record<string, Route>) {
  const parsed = Object.keys(routes).map((k) => {
    const [m, p] = k.includes(' ') ? k.split(' ', 2) : ['GET', k];
    return { k, m, p };
  }).sort((a, b) => b.p.length - a.p.length);
  const fn = vi.fn(async (rawUrl: string, init: RequestInit = {}) => {
    const url = unbook(String(rawUrl));
    const method = (init.method ?? 'GET').toUpperCase();
    const hit = parsed.find((r) => r.m === method && url.startsWith(r.p));
    if (!hit) return reply({ error: 'Not found.' }, 404);
    const r = routes[hit.k];
    return typeof r === 'function' ? (r as Handler)(url, init) : reply(r);
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

/** The calls a stub received for one method and path prefix, with parsed JSON bodies. */
export function callsTo(fn: ReturnType<typeof stubFetch>, method: string, path: string): { url: string; body: unknown; init: RequestInit }[] {
  return fn.mock.calls
    .map(([url, init]) => ({ url: unbook(url as string), init: (init ?? {}) as RequestInit }))
    .filter((c) => (c.init.method ?? 'GET').toUpperCase() === method && c.url.startsWith(path))
    .map((c) => ({ ...c, body: typeof c.init.body === 'string' ? JSON.parse(c.init.body) : c.init.body }));
}

export type Entry = string | { pathname: string; state?: unknown };

const client = () => new QueryClient({ defaultOptions: { queries: { retry: false } } });

export function wrap(ui: ReactElement, path: Entry = '/', qc = client()) {
  const result = render(
    <QueryClientProvider client={qc}><MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter></QueryClientProvider>,
  );
  return { qc, ...result };
}

export const BOOK: BookSummary = { slug: 'ours', name: 'Ours', kind: 'household', role: 'manager', available: true, reason: null, owners: [
  { key: 'jr', label: 'JR' }, { key: 'spouse', label: 'Sam' }, { key: 'joint', label: 'Joint' }, { key: 'business', label: 'Business' }], profile: null };

/** Review focus: the signed-in person, user 1, whose Review view is kept per person on this device (P1). */
export const ME: Me = { user: { id: 1, username: 'jr', display_name: 'JR', email: 'jr@example.com' }, books: [BOOK],
  session: { id: 1, device_label: 'Laptop', created_at: '2026-10-01T00:00:00Z' } };

/** Review in the list view: saves user 1's choice and returns the route that says who is signed in. Spread it into
 *  stubFetch for a test of the list: `stubFetch({ ...inList(), '/api/review': … })`. */
export function inList(): Record<string, Route> {
  localStorage.setItem('steward-review-view:1', 'list');
  return { '/api/auth/me': ME };
}

/** Like wrap, inside a book (the household book "ours" unless `book` says otherwise). */
export function wrapBook(ui: ReactElement, book: Partial<BookSummary> = {}, path: Entry = '/b/ours') {
  return wrap(<BookCtx.Provider value={{ ...BOOK, ...book }}>{ui}</BookCtx.Provider>, path);
}

/** Like wrapBook, at `path` in the book ('/settings/people', or a full '/b/…' address), and returns `location`, a ref
 *  that follows the router, so a test can see where a redirect went. With `books`, the signed-in person (the ['me']
 *  query) is in those books, from the cache, so the test's own stubFetch routes stay as they are. */
export function renderAt(ui: ReactElement, book: Partial<BookSummary>, path: Entry, books?: BookSummary[]) {
  const location = {} as { current: Location };
  function Follow() {
    location.current = useLocation();
    return null;
  }
  const open = { ...BOOK, ...book };
  const qc = client();
  if (books) {
    const me: Me = { user: { id: 1, username: 'jr', display_name: 'JR', email: 'jr@example.com' }, books,
      session: { id: 1, device_label: 'Laptop', created_at: '2026-10-01T00:00:00Z' } };
    qc.setQueryData(['me'], me);
  }
  const inBook = (p: string) => (p.startsWith('/b/') ? p : bookHref(open.slug, p));
  const at: Entry = typeof path === 'string' ? inBook(path) : { ...path, pathname: inBook(path.pathname) };
  return { ...wrap(<BookCtx.Provider value={open}>{ui}<Follow /></BookCtx.Provider>, at, qc), location };
}
