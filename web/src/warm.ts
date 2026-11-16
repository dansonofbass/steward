import type { QueryClient, QueryKey } from '@tanstack/react-query';
import { matchRoutes, type createBrowserRouter, type RouteObject } from 'react-router-dom';
import { currentBook, setCurrentBook } from './api/book';
import { api } from './api/client';

/** Phase 18: a screen's data waited for /me, then for the screen's code, and Plan's second wave for /plan. Each route's
 *  `handle.warm` names what its screen asks for as it opens; warm() starts all of it, and /me, as the address is
 *  reached. The screen's own hooks find the requests in flight or answered under the same keys and options. */
export type Params = Record<string, string | undefined>;
export type Want = { key: QueryKey; path: string; options?: { staleTime?: number; retry?: false } };
export type At = { pathname: string; search: string; key: string };
export type Warm = {
  code?: (params: Params) => Promise<unknown> | undefined;
  wants?: (params: Params, search: URLSearchParams) => Want[];
  run?: (at: At) => void;
};

export function warm(table: RouteObject[], qc: QueryClient, at: At): void {
  const matches = matchRoutes(table, at.pathname) ?? [];
  // A screen's code needs no book: Forgot, Reset and the invitation start theirs here too (WEB-19).
  for (const m of matches) void (m.route.handle as { warm?: Warm } | undefined)?.warm?.code?.(m.params)?.catch(() => undefined);
  const slug = matches.find((m) => m.params.slug)?.params.slug;
  if (!slug) return;                                  // sign-in and the old addresses: no book to start data in
  if (currentBook() !== slug) setCurrentBook(slug);
  // useMe's own key and options, so RequireAuth's query is this one.
  void qc.prefetchQuery({ queryKey: ['me'], queryFn: () => api('/api/auth/me'), retry: false, staleTime: 60_000 });
  const search = new URLSearchParams(at.search);
  for (const m of matches) {
    const w = (m.route.handle as { warm?: Warm } | undefined)?.warm;
    if (!w) continue;   // its code started above; a chunk that fails fails again, the usual way, as it renders
    w.run?.(at);
    for (const x of w.wants?.(m.params, search) ?? []) {
      void qc.prefetchQuery({ queryKey: x.key, queryFn: () => api(x.path), ...x.options });
    }
  }
}

/** Warms the address the app opens at, then each one the router reaches (a new history entry, once). */
export function startWarming(router: ReturnType<typeof createBrowserRouter>, table: RouteObject[], qc: QueryClient): () => void {
  let last: string | null = null;
  const go = (at: At) => {
    if (at.key === last) return;
    last = at.key;
    warm(table, qc, at);
  };
  go(router.state.location);
  return router.subscribe((state) => go(state.location));
}
