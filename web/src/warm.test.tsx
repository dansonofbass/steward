import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider, type RouteObject } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { currentBook } from './api/book';
import { makeQueryClient } from './queryClient';
import { routes } from './routes';
import { OCT } from './screens/spending/fixtures';
import { ME, stubFetch, type Route } from './test-utils';
import { startWarming, warm, type Params } from './warm';

const stops: (() => void)[] = [];
afterEach(() => { stops.splice(0).forEach((stop) => stop()); });
const urls = (fn: ReturnType<typeof stubFetch>) => fn.mock.calls.map(([u]) => String(u));
const pending = () => new Promise<Response>(() => {});
const REVIEW = { uncategorized: [], count: 0, duplicates: [], duplicate_count: 0, top_categories: [] };

/** The app's routes at `path`, warmed as App.tsx warms them. /me never answers unless `extra` says otherwise. */
function open(path: string, extra: Record<string, Route> = {}) {
  const fetchMock = stubFetch({ '/api/auth/me': pending, ...extra });
  const qc = makeQueryClient();
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  stops.push(startWarming(router, routes, qc));
  render(<QueryClientProvider client={qc}><RouterProvider router={router} /></QueryClientProvider>);
  return { fetchMock, router };
}

describe('the warm-up (phase 18)', () => {
  it("asks for Plan's plan, facts and next dollar, and the review count, before /me answers", async () => {
    const { fetchMock } = open('/b/ours/plan');
    await waitFor(() => expect(urls(fetchMock)).toEqual(expect.arrayContaining(
      ['/api/auth/me', '/api/b/ours/review', '/api/b/ours/plan', '/api/b/ours/facts', '/api/b/ours/next-dollar'])));
    expect(screen.getByTestId('auth-loading')).toBeInTheDocument();     // RequireAuth still waits for /me
  });

  it("asks for Home's growth tree with its other requests (phase 17 spec 3.4)", async () => {
    const { fetchMock } = open('/b/ours');
    await waitFor(() => expect(urls(fetchMock)).toEqual(expect.arrayContaining(['/api/b/ours/accounts', '/api/b/ours/growth'])));
  });

  it("asks for Spending's month from the address, and the accounts", async () => {
    const { fetchMock } = open('/b/ours/spending?month=2026-09');
    await waitFor(() => expect(urls(fetchMock)).toEqual(expect.arrayContaining(
      ['/api/b/ours/spending?month=2026-09', '/api/b/ours/accounts'])));
    expect(screen.getByTestId('auth-loading')).toBeInTheDocument();
  });

  it("asks for Import's lists on Settings › Import", async () => {
    const { fetchMock } = open('/b/ours/settings/import');
    await waitFor(() => expect(urls(fetchMock)).toEqual(expect.arrayContaining(
      ['/api/b/ours/accounts', '/api/b/ours/import/batches', '/api/b/ours/import/layouts'])));
  });

  it('warms each address the router reaches, before anything renders it', async () => {
    const { fetchMock, router } = open('/b/ours/review');
    await router.navigate('/b/ours/plan');
    await waitFor(() => expect(urls(fetchMock)).toContain('/api/b/ours/plan'));
    expect(screen.getByTestId('auth-loading')).toBeInTheDocument();
  });

  it('Spending asks for its month, the accounts, the review count and /me once each', async () => {
    const { fetchMock } = open('/b/ours/spending', {
      '/api/auth/me': ME, '/api/spending': OCT, '/api/accounts': { accounts: [] }, '/api/review': REVIEW });
    expect(await screen.findByRole('heading', { level: 1, name: 'October 2026' })).toBeInTheDocument();
    const asked = urls(fetchMock);
    for (const u of ['/api/auth/me', '/api/b/ours/spending', '/api/b/ours/accounts', '/api/b/ours/review']) {
      expect(asked.filter((x) => x === u), u).toHaveLength(1);
    }
  });

  it("starts each matched route's code and requests, in the book the address names", async () => {
    const fetchMock = stubFetch({});
    const code = vi.fn(() => Promise.resolve());
    const table: RouteObject[] = [{ path: '/b/:slug', handle: { warm: { wants: () => [{ key: ['x'], path: '/api/x' }] } }, children: [
      { path: 'y/:id', handle: { warm: { code, wants: (p: Params) => [{ key: ['y', p.id], path: `/api/y/${p.id}` }] } } }] }];
    warm(table, makeQueryClient(), { pathname: '/b/lake/y/7', search: '', key: 'k' });
    expect(currentBook()).toBe('lake');
    expect(code).toHaveBeenCalledWith({ slug: 'lake', id: '7' });
    await waitFor(() => expect(urls(fetchMock)).toEqual(['/api/auth/me', '/api/b/lake/x', '/api/b/lake/y/7']));
  });

  it('an address outside a book asks for no data', () => {
    const fetchMock = stubFetch({});
    warm(routes, makeQueryClient(), { pathname: '/login', search: '', key: 'k' });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(currentBook()).toBe('ours');
  });

  it("an address outside a book still starts its screen's code (Forgot, Reset, the invitation; WEB-19)", () => {
    const fetchMock = stubFetch({});
    const code = vi.fn(() => Promise.resolve());
    warm([{ path: '/forgot', handle: { warm: { code } } }], makeQueryClient(), { pathname: '/forgot', search: '', key: 'k' });
    expect(code).toHaveBeenCalledOnce();
    expect(fetchMock).not.toHaveBeenCalled();
    for (const path of ['/forgot', '/reset', '/invite']) {
      const hit = (function find(t: RouteObject[]): RouteObject | undefined {
        for (const r of t) { if (r.path === path) return r; const c = r.children && find(r.children); if (c) return c; }
        return undefined;
      })(routes);
      expect((hit?.handle as { warm?: { code?: unknown } })?.warm?.code, path).toBeTypeOf('function');
    }
  });
});
