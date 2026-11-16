import { useEffect, useState } from 'react';
import { currentBook } from '../api/book';
import type { Background } from '../api/types';

// Phase 17 spec 3.7: the gateway coming back. The last background answer each book showed this visit, on any screen, so
// Home and Review never both say it for the same return.
const last = new Map<string, boolean>();
export function forgetGatewayWatch(): void { last.clear(); }

/** True once: the last answer this visit saw for the book was waiting, and this one isn't and has rows to catch up. */
export function gatewayTurned(book: string, bg: Background): boolean {
  const was = last.get(book);
  last.set(book, bg.waiting);
  return was === true && !bg.waiting && bg.pending > 0;
}

export function useGatewayBack(bg: Background): boolean {
  const [back, setBack] = useState(false);
  useEffect(() => { if (gatewayTurned(currentBook() ?? '', bg)) setBack(true); }, [bg.waiting, bg.pending]); // eslint-disable-line react-hooks/exhaustive-deps
  return back;
}
