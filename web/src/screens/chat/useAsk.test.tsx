import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setCurrentBook } from '../../api/book';
import type { AboutIn } from '../../ask/about';
import { callsTo, stubFetch } from '../../test-utils';
import type { AboutWire } from './askApi';
import { useAsk } from './useAsk';

afterEach(() => { vi.unstubAllGlobals(); setCurrentBook('ours'); });

const WIRE: AboutWire = { kind: 'category', category: 'dining', month: '2026-10' };
const DONE = { type: 'done', stop: 'end_turn', line: null, answer: 'Yes.', long_line: null, conversation_id: 7, turn_id: 't_1',
  requests: 1, cost_cents: 4, parts: 2, bytes: 900, meta: '3 seconds · $0.04' };
const turn = () => new Response(`${JSON.stringify({ type: 'conversation', id: 7, note: null, turn_id: 't_1' })}\n${JSON.stringify(DONE)}\n`,
  { status: 200, headers: { 'content-type': 'application/x-ndjson' } });
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>
);

describe('useAsk with an about (Ask about this, Privacy tests: Web)', () => {
  it('sends only the request’s own keys, whatever it was given, and keeps the wire for the About line', async () => {
    const fetchMock = stubFetch({ 'POST /api/chat/ask': () => turn() });
    const { result } = renderHook(() => useAsk(null, () => {}), { wrapper });
    const forged = { kind: 'category', category: 'dining', month: '2026-10', label: 'Eating out', note: 'zorblax' } as unknown as AboutIn;
    await act(async () => { await result.current.ask('Why?', forged, WIRE); });
    expect(callsTo(fetchMock, 'POST', '/api/chat/ask')[0].body)
      .toEqual({ question: 'Why?', conversation_id: null, about: { kind: 'category', category: 'dining', month: '2026-10' } });
    expect(result.current.live?.about).toEqual(WIRE);
  });
  it('sends no about when there is none', async () => {
    const fetchMock = stubFetch({ 'POST /api/chat/ask': () => turn() });
    const { result } = renderHook(() => useAsk(null, () => {}), { wrapper });
    await act(async () => { await result.current.ask('Why?'); });
    expect(callsTo(fetchMock, 'POST', '/api/chat/ask')[0].body).toEqual({ question: 'Why?', conversation_id: null });
    expect(result.current.live?.about).toBeNull();
  });
});
