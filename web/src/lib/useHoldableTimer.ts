import { useEffect, useRef } from 'react';

/** Sorting redesign, After: "Undone." stays about 2 seconds. */
export const UNDONE_MS = 2000;

/** Calls `done` `ms` after `run` last changed, paused while `held`; nothing while `run` is null. A pause keeps what was
 *  left, so the time resumes rather than restarts. */
export function useHoldableTimer(run: number | null, ms: number, held: boolean, done: () => void) {
  const left = useRef(ms);
  const cb = useRef(done);
  cb.current = done;
  useEffect(() => { left.current = ms; }, [run, ms]);
  useEffect(() => {
    if (run === null || held) return;
    const start = Date.now();
    const id = window.setTimeout(() => { cb.current(); }, left.current);
    return () => { window.clearTimeout(id); left.current = Math.max(0, left.current - (Date.now() - start)); };
  }, [run, held]);
}
