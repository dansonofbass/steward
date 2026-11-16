// POST /chat/ask answers NDJSON, one event per line (plan B, "The turn stream after plan B"). A refused question
// (chat off, too long, the gateway not set up) comes back as an error status with the server's plain line.
import { resolveApiPath } from '../../api/book';
import { ApiError, NETWORK_MESSAGE, unauthorized } from '../../api/client';
import type { AboutIn } from '../../ask/about';
import type { AskEvent } from './askApi';
import { STREAM_BROKE, STREAM_GARBLED } from './copy';

export async function readTurn(body: { question: string; conversation_id: number | null; about?: AboutIn }, onEvent: (e: AskEvent) => void,
  signal: AbortSignal): Promise<void> {
  let res: Response;
  try {
    res = await fetch(resolveApiPath('/api/chat/ask'), {
      method: 'POST', credentials: 'same-origin', signal, body: JSON.stringify(body),
      headers: { 'Content-Type': 'application/json', Accept: 'application/x-ndjson' },
    });
  } catch (e) {
    if (signal.aborted) throw e;
    throw new ApiError(0, NETWORK_MESSAGE);
  }
  if (res.status === 401) unauthorized();
  if (!res.ok) {
    let message = `Something went wrong (${res.status}).`;
    let parsed: unknown = null;
    try {
      parsed = await res.json();
      const error = (parsed as { error?: unknown } | null)?.error;
      if (typeof error === 'string') message = error;
    } catch { /* not JSON; keep the generic line */ }
    throw new ApiError(res.status, message, parsed);
  }
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  // A broken connection or a line that isn't JSON ends the turn with a plain line, never "Failed to fetch" or a
  // SyntaxError's text (final review, Tasks 10 and 13).
  const parse = (line: string): AskEvent => {
    try { return JSON.parse(line) as AskEvent; } catch { throw new ApiError(0, STREAM_GARBLED); }
  };
  let buf = '';
  for (;;) {
    let chunk: ReadableStreamReadResult<Uint8Array>;
    try {
      chunk = await reader.read();
    } catch (e) {
      if (signal.aborted) throw e;
      throw new ApiError(0, STREAM_BROKE);
    }
    if (chunk.done) break;
    buf += decoder.decode(chunk.value, { stream: true });
    let nl = buf.indexOf('\n');
    while (nl >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (line) onEvent(parse(line));
      nl = buf.indexOf('\n');
    }
  }
  const rest = (buf + decoder.decode()).trim();
  if (rest) onEvent(parse(rest));
}
