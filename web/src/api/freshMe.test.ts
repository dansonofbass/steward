// The flaky e2e "Remove, Undo, Remove": a fresh /me asked with fetchQuery joined a /me already on its way, asked before
// the Sample was restored, so the book list came back without it. Every fresh /me goes through freshMe (api/hooks.ts),
// which drops a request on its way first. A scan fails on a hand-rolled one.
import { describe, expect, it } from 'vitest';

const SOURCES: Record<string, string> = Object.fromEntries(
  Object.entries(import.meta.glob<string>('/src/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }))
    .filter(([path]) => !/\.test\.[jt]sx?$/.test(path)),
);

const HAND_ROLLED = /\bfetchQuery\(\s*\{\s*queryKey:\s*\[\s*'me'\s*\]/;

const handRolled = (sources: Record<string, string>) =>
  Object.entries(sources).filter(([path, src]) => path !== '/src/api/hooks.ts' && HAND_ROLLED.test(src)).map(([path]) => path);

describe('a fresh /me goes through freshMe', () => {
  it('no file asks for /me with fetchQuery itself', () => {
    expect(handRolled(SOURCES)).toEqual([]);
  });

  it('catches one that does', () => {
    expect(handRolled({ '/src/x.tsx': "await qc.fetchQuery({ queryKey: ['me'], queryFn: () => api('/api/auth/me'), staleTime: 0 });" })).toEqual(['/src/x.tsx']);
  });
});
