import { useCallback, useMemo, useRef, useState } from 'react';

export type Removal = {
  /** What the line says now; empty until something is removed. */
  line: string;
  /** Counts the lines said. RemovalLine keys its <p> on it, so a line the same as the last one is a new node a screen
   *  reader hears again (removing a second "Vee" says "Removed Vee from Mom." twice). */
  seq: number;
  /** A callback ref for where focus goes after a removal: the list's heading (give it tabIndex={-1}), or the line itself
   *  (RemovalLine's holdsFocus) when the list can vanish with its last row. */
  anchor: (el: HTMLElement | null) => void;
  /** The removal went through and its confirm sheet is about to close: say so, and the sheet gives focus to the anchor. */
  removed: (text: string) => void;
  /** An inline confirm with no sheet: say so and move focus to the anchor now. */
  removedHere: (text: string) => void;
  /** A line that moves no focus (an add, a change). */
  say: (text: string) => void;
  clear: () => void;
  /** ConfirmSheet's returnTo: the anchor after a removal, the button that opened the sheet after a cancel. */
  returnTo: () => HTMLElement | null;
};

/** After a confirmed removal (THO-1): a line saying what went, in a status a screen reader hears, and a place for focus
 *  that still exists. The sheet's default gives focus back to what opened it, which is the gone row's own button, so
 *  focus would fall to the page body and the next Tab would start from the top of the page. */
export function useRemoval(): Removal {
  const el = useRef<HTMLElement | null>(null);
  const gone = useRef(false);
  // A new object each time, with a count, so saying the same text again still renders: useState skips an equal value.
  const [{ line, seq }, setSaid] = useState({ line: '', seq: 0 });
  const setLine = useCallback((text: string) => setSaid((was) => ({ line: text, seq: was.seq + 1 })), []);
  const anchor = useCallback((node: HTMLElement | null) => { el.current = node; }, []);
  const removed = useCallback((text: string) => { gone.current = true; setLine(text); }, [setLine]);
  const removedHere = useCallback((text: string) => { setLine(text); el.current?.focus(); }, [setLine]);
  const say = useCallback((text: string) => setLine(text), [setLine]);
  const clear = useCallback(() => setLine(''), [setLine]);
  const returnTo = useCallback(() => {
    const after = gone.current;
    gone.current = false;
    return after ? el.current : null;
  }, []);
  return useMemo(() => ({ line, seq, anchor, removed, removedHere, say, clear, returnTo }), [line, seq, anchor, removed, removedHere, say, clear, returnTo]);
}

/** ConfirmSheet's returnTo for a sheet whose opener is still there after the confirm (a role change keeps its select;
 *  signing out leaves the page). The removal guard (removalFocus.test.ts) lists each use with its reason. */
export const BACK_TO_OPENER = (): HTMLElement | null => null;
