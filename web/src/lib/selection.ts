import { useCallback, useEffect, useRef, useState, type MouseEvent, type PointerEvent } from 'react';

/** Bulk sort (profile spec, Sorting several rows at once): the server sorts up to 200 rows in one action. */
export const SORT_MAX = 200;
/** A touch held this long on a row starts a selection with that row picked. */
export const LONG_PRESS_MS = 500;

const NONE: ReadonlySet<number> = new Set();

/** The picked rows after a click on `id`: it flips, or with `from` (Shift, and the row clicked before) every row from
 *  there to here in the list's order is picked. */
export function picked(was: ReadonlySet<number>, order: readonly number[], id: number, from: number | null): ReadonlySet<number> {
  const a = from === null ? -1 : order.indexOf(from);
  const b = order.indexOf(id);
  const next = new Set(was);
  if (a < 0 || b < 0) {
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  }
  for (const i of order.slice(Math.min(a, b), Math.max(a, b) + 1)) next.add(i);
  return next;
}

/** Selection mode for a list: `order` reads the rows on screen, top to bottom, when a Shift-click needs them. */
export function useSelection(order: () => readonly number[]) {
  const [on, setOn] = useState(false);
  const [ids, setIds] = useState<ReadonlySet<number>>(NONE);
  const anchor = useRef<number | null>(null);
  const read = useRef(order);
  read.current = order;
  const start = useCallback((first?: number) => {
    setOn(true);
    setIds(first === undefined ? NONE : new Set([first]));
    anchor.current = first ?? null;
  }, []);
  const end = useCallback(() => { setOn(false); setIds(NONE); anchor.current = null; }, []);
  const pick = useCallback((id: number, range: boolean) => {
    const from = range ? anchor.current : null;
    setIds((was) => picked(was, read.current(), id, from));
    anchor.current = id;
  }, []);
  const keep = useCallback((only: readonly number[]) => { setIds(new Set(only)); anchor.current = null; }, []);
  return { on, ids, start, end, pick, keep };
}

/** A long press on a phone: handlers for the list, which find the row by its data-id. The click that ends the press is
 *  swallowed, so it neither opens the row nor flips it back (the handlers stay on after the selection starts). Mouse
 *  and pen never start one; with `onLong` null nothing starts. */
export function useLongPress(onLong: ((id: number) => void) | null) {
  const timer = useRef(0);
  const fired = useRef(false);
  const run = useRef(onLong);
  run.current = onLong;
  const stop = () => { window.clearTimeout(timer.current); };
  useEffect(() => stop, []);
  return {
    onPointerDown: (e: PointerEvent<HTMLElement>) => {
      fired.current = false;
      stop();
      const row = (e.target as Element).closest<HTMLElement>('[data-id]');
      if (e.pointerType !== 'touch' || !row || !run.current) return;
      const id = Number(row.dataset.id);
      timer.current = window.setTimeout(() => { fired.current = true; navigator.vibrate?.(10); run.current?.(id); }, LONG_PRESS_MS);
    },
    onPointerUp: stop,
    onPointerCancel: stop,
    onPointerLeave: stop,
    onClickCapture: (e: MouseEvent<HTMLElement>) => {
      if (!fired.current) return;
      fired.current = false;
      e.preventDefault();
      e.stopPropagation();
    },
    onContextMenu: (e: MouseEvent<HTMLElement>) => { if (fired.current) e.preventDefault(); },
  };
}
