import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { HOME } from '../screens/home/fixtures';
import { callsTo, stubFetch } from '../test-utils';
import { forgetHome, useHome, warmHome, type HomeData } from './home';

afterEach(() => { vi.unstubAllGlobals(); forgetHome(); });
const SINCE = { from: '2026-10-27T19:00:00+00:00', from_day: '2026-10-27', over_month: false, lines: [], more: 0, net_worth_cents: null };

function mount(entry: { pathname: string; key: string } = { pathname: '/b/ours', key: 'visit' }, qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}><MemoryRouter initialEntries={[entry]}>{children}</MemoryRouter></QueryClientProvider>
  );
  return renderHook(() => useHome(), { wrapper });
}

describe('useHome (Home spec P29)', () => {
  it("sends the first answer's since.from with every refetch in the visit", async () => {
    const fetchMock = stubFetch({ '/api/home': { ...HOME, since: SINCE } });
    const { result } = mount();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    await act(async () => { await result.current.refetch(); });
    expect(callsTo(fetchMock, 'GET', '/api/home').map((c) => c.url)).toEqual(['/api/home', `/api/home?from=${encodeURIComponent(SINCE.from)}`]);
  });

  it('a first visit keeps no Since for the whole visit, whatever a refetch brings', async () => {
    let answer: HomeData = HOME;
    const fetchMock = stubFetch({ '/api/home': () => new Response(JSON.stringify(answer), { status: 200, headers: { 'content-type': 'application/json' } }) });
    const { result } = mount();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    answer = { ...HOME, since: SINCE };
    await act(async () => { await result.current.refetch(); });
    expect(result.current.data?.since).toBeNull();
    expect(callsTo(fetchMock, 'GET', '/api/home').map((c) => c.url)).toEqual(['/api/home', '/api/home']);
  });
});

describe('the warm-up hands Home its first answer (phase 18)', () => {
  it("takes the warm-up's answer as the visit's first, and sends its since.from after", async () => {
    const fetchMock = stubFetch({ '/api/home': { ...HOME, since: SINCE } });
    warmHome('visit');
    const { result } = mount({ pathname: '/b/ours', key: 'visit' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    await act(async () => { await result.current.refetch(); });
    expect(callsTo(fetchMock, 'GET', '/api/home').map((c) => c.url)).toEqual(['/api/home', `/api/home?from=${encodeURIComponent(SINCE.from)}`]);
  });

  it('a Home at another history entry asks for itself', async () => {
    const fetchMock = stubFetch({ '/api/home': HOME });
    warmHome('elsewhere');
    const { result } = mount({ pathname: '/b/ours', key: 'visit' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(callsTo(fetchMock, 'GET', '/api/home')).toHaveLength(2);   // the warm-up's, unused, and the mount's own
  });

  it("a Home mounted over a fresh cached answer still takes the warm-up's as its first, asking once", async () => {
    const fetchMock = stubFetch({ '/api/home': { ...HOME, since: SINCE } });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 60_000 } } });
    qc.setQueryData(['home'], HOME);
    warmHome('visit');
    const { result } = mount({ pathname: '/b/ours', key: 'visit' }, qc);
    await waitFor(() => expect(result.current.data?.since).toEqual(SINCE));
    expect(callsTo(fetchMock, 'GET', '/api/home')).toHaveLength(1);
  });
});
