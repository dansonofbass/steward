import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, setUnauthorizedHandler } from '../../api/client';
import { setCurrentBook } from '../../api/book';
import type { AskEvent } from './askApi';
import { readTurn } from './stream';

afterEach(() => { vi.unstubAllGlobals(); setCurrentBook('ours'); setUnauthorizedHandler(null); });

function streaming(chunks: string[], status = 200) {
  const body = new ReadableStream<Uint8Array>({
    start(c) { const enc = new TextEncoder(); chunks.forEach((s) => c.enqueue(enc.encode(s))); c.close(); },
  });
  return vi.fn(async (_url: string, _init?: RequestInit) => new Response(body,{ status, headers: { 'content-type': 'application/x-ndjson' } }));
}

describe('readTurn', () => {
  it('parses one event per line even when a line is split across chunks', async () => {
    const fetchMock = streaming(['{"type":"conversation","id":3,"note":null,"turn_id":"t_1"}\n{"type":"te', 'xt","delta":"Hi"}\n',
      '{"type":"done","stop":"end_turn"}']);
    vi.stubGlobal('fetch', fetchMock);
    const seen: AskEvent[] = [];
    await readTurn({ question: 'Q', conversation_id: null }, (e) => seen.push(e), new AbortController().signal);
    expect(seen.map((e) => e.type)).toEqual(['conversation', 'text', 'done']);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/b/ours/chat/ask');
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({ question: 'Q', conversation_id: null });
  });

  it('turns an error status into an ApiError with the server line', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: 'Chat is off for this book. A manager can turn it on in Settings → Chat.' }), { status: 409 })));
    await expect(readTurn({ question: 'Q', conversation_id: null }, () => {}, new AbortController().signal))
      .rejects.toMatchObject({ status: 409, message: 'Chat is off for this book. A manager can turn it on in Settings → Chat.' });
    expect(ApiError).toBeDefined();
  });

  it('a 401 sends the person to sign in, like every other request', async () => {
    const signIn = vi.fn();
    setUnauthorizedHandler(signIn);
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: 'Sign in again.' }), { status: 401 })));
    await expect(readTurn({ question: 'Q', conversation_id: null }, () => {}, new AbortController().signal)).rejects.toMatchObject({ status: 401 });
    expect(signIn).toHaveBeenCalledTimes(1);
  });

  it('a stream that breaks or garbles ends with a plain line, never the browser\'s own error text', async () => {
    const broken = new ReadableStream<Uint8Array>({
      start(c) { c.enqueue(new TextEncoder().encode('{"type":"text","delta":"Hi"}\n')); c.error(new TypeError('Failed to fetch')); },
    });
    vi.stubGlobal('fetch', vi.fn(async () => new Response(broken, { status: 200 })));
    const err = await readTurn({ question: 'Q', conversation_id: null }, () => {}, new AbortController().signal).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toBe("The answer stopped arriving. Check that this device is on your home network or Tailscale, then ask again.");
    vi.stubGlobal('fetch', streaming(['{"type":"text","de\n']));
    const bad = await readTurn({ question: 'Q', conversation_id: null }, () => {}, new AbortController().signal).catch((e) => e);
    expect(bad).toBeInstanceOf(ApiError);
    expect(bad.message).toBe("Steward sent part of this answer in a form the page couldn't read, so it stopped. Ask again.");
  });
});
