import { useEffect, useRef, useState } from 'react';
import { isAbort } from '../api/client';

/** Spec 7: lever drags are debounced at 150 ms. The only debounce in the app. */
export const DEBOUNCE_MS = 150;

export type Request<T> = { key: string; run: (signal: AbortSignal) => Promise<T> } | null;
export type RequestState<T> = { key: string | null; data: T | undefined; error: unknown; pending: boolean };

/**
 * Runs the newest request `delay` ms after its key stops changing. A new key aborts the request in flight, and an
 * aborted request's answer never lands. `key` in the state says which request `data`/`error` belong to.
 */
export function useDebouncedRequest<T>(req: Request<T>, delay = DEBOUNCE_MS): RequestState<T> {
  const [state, setState] = useState<RequestState<T>>({ key: null, data: undefined, error: null, pending: false });
  const run = useRef(req?.run);
  run.current = req?.run;
  const key = req?.key ?? null;

  useEffect(() => {
    if (key === null) {
      setState((s) => (s.pending ? { ...s, pending: false } : s));
      return;
    }
    setState((s) => ({ ...s, pending: true }));
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      const fn = run.current;
      if (!fn) return;
      fn(ctrl.signal).then(
        (data) => { if (!ctrl.signal.aborted) setState({ key, data, error: null, pending: false }); },
        (error: unknown) => {
          if (ctrl.signal.aborted || isAbort(error)) return;
          setState((s) => ({ ...s, key, error, pending: false }));
        },
      );
    }, delay);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [key, delay]);

  return state;
}
