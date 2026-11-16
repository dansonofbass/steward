// POST /chat/about for the chip (Ask about this P8): once per open and again on add-back (each a new `nonce`). A 409
// means chat was turned off elsewhere: the status and the book are refreshed, so the off state shows and the Ask
// button goes (P31). A 404 is the gone line (P28). Anything else shows no chip, and the question can still go without
// it. While a new answer for the same thing is coming, the last one stays, so a removed chip keeps its words.
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { ApiError, isAbort } from '../../api/client';
import { aboutParam, type AboutIn } from '../../ask/about';
import { aboutPreview, type AboutReply } from './askApi';
import { ABOUT_GONE } from './copy';

export type AboutState = { status: 'none' | 'loading' | 'ready' | 'gone' | 'failed'; reply: AboutReply | null; line: string | null };
const NONE: AboutState = { status: 'none', reply: null, line: null };

export function useAboutReply(about: AboutIn | null, nonce: number): AboutState {
  const qc = useQueryClient();
  const [state, setState] = useState<AboutState>(NONE);
  const param = about ? aboutParam(about) : null;
  const seen = useRef<string | null>(null);
  useEffect(() => {
    if (!about) { seen.current = null; setState(NONE); return; }
    const c = new AbortController();
    // The last answer stays across a nonce bump for the same thing; a different thing starts clean.
    const same = seen.current === param;
    seen.current = param;
    setState((s) => (same ? { ...s, status: 'loading' } : { status: 'loading', reply: null, line: null }));
    aboutPreview(about, c.signal).then(
      (reply) => { if (!c.signal.aborted) setState({ status: 'ready', reply, line: null }); },
      (e: unknown) => {
        if (c.signal.aborted || isAbort(e)) return;
        if (e instanceof ApiError && e.status === 409) {
          // A fetch still in flight (the panel's own, started with this one) would land with the old answer and an
          // invalidation can't replace it, so it is cancelled first.
          for (const queryKey of [['chat', 'status'], ['me']]) void qc.cancelQueries({ queryKey }).then(() => qc.invalidateQueries({ queryKey }));
        }
        setState(e instanceof ApiError && e.status === 404
          ? { status: 'gone', reply: null, line: e.message || ABOUT_GONE } : { status: 'failed', reply: null, line: null });
      });
    return () => { c.abort(); };
  }, [param, nonce]); // eslint-disable-line react-hooks/exhaustive-deps
  return state;
}
