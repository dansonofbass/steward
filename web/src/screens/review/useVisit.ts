import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useReducer, useRef, useState } from 'react';
import { api, ApiError } from '../../api/client';
import type { Txn, UndoReply } from '../../api/types';
import type { ReviewView } from '../../lib/reviewPrefs';
import { plainToast, type ToastBody } from './toastText';
import { type Entry, entryOf, entryWithToken, type Kind, stackReducer, topOf } from './undoStack';

export type Shown = { key: number; entry: string | null; body: ToastBody };
const messageOf = (err: unknown) => (err instanceof Error ? err.message : 'Something went wrong.');

/** The card Undo brings back, as it showed (P15): the reply's row over the stored card, keeping what only Review's queue
 *  sends (why it is here, the guess, the "N like it" count, whether Reimbursable is offered). Engineering choice 3. */
export function rebuilt(card: Txn, t: Txn | null): Txn {
  if (!t) return card;
  return { ...card, ...t, reason: card.reason, guess: card.guess, matching: card.matching, reimburse_ok: card.reimburse_ok };
}

/** One Review visit (review focus, Undo P14 and The toast P16): the stack both views share, the rows that left the
 *  queue this visit (N left and the progress bar), and the one toast. It lives while Review is mounted, so leaving
 *  Review clears it; the server's tokens still expire on their own. `onUndone` hears each Undo that worked, with the
 *  card rebuilt (null for a bulk sort or a note). */
export function useVisit(onUndone: (e: Entry, card: Txn | null) => void) {
  const qc = useQueryClient();
  const [stack, dispatch] = useReducer(stackReducer, []);
  const live = useRef(stack);
  live.current = stack;
  const [left, setLeft] = useState<ReadonlySet<number>>(() => new Set());
  const [toast, setToast] = useState<Shown | null>(null);
  const [undoing, setUndoing] = useState(false);
  const seq = useRef(0);
  const tokens = useRef(new Map<string, string | null>());     // null: in flight
  const waiting = useRef(new Map<string, ((token: string | null) => void)[]>());
  const busy = useRef(false);
  const heard = useRef(onUndone);
  heard.current = onUndone;

  const wake = (id: string, token: string | null) => {
    for (const w of waiting.current.get(id) ?? []) w(token);
    waiting.current.delete(id);
  };
  const move = (ids: readonly number[], gone: boolean) => setLeft((s) => {
    const n = new Set(s);
    for (const i of ids) { if (gone) n.add(i); else n.delete(i); }
    return n;
  });
  const drop = (id: string) => { tokens.current.delete(id); dispatch({ type: 'drop', id }); };

  /** An action is going out: a pending entry, so an Undo pressed now waits for its token. */
  const begin = useCallback((kind: Kind, card: Txn | null, view: ReviewView): string => {
    const id = `e${++seq.current}`;
    tokens.current.set(id, null);
    dispatch({ type: 'push', entry: { id, token: null, kind, ids: card ? [card.id] : [], card, view } });
    return id;
  }, []);

  /** The reply landed: the entry takes its token and rows; with `leaves`, those rows left the queue (even when the reply
   *  carried no token, so "N left" stays right). */
  const done = useCallback((id: string, token: string | null, ids: readonly number[], leaves: boolean) => {
    if (leaves) move(ids, true);
    if (token === null) { drop(id); wake(id, null); return; }
    tokens.current.set(id, token);
    dispatch({ type: 'settle', id, token, ids: [...ids] });
    wake(id, token);
  }, []);

  const fail = useCallback((id: string) => { drop(id); wake(id, null); }, []);
  const say = useCallback((entry: string | null, body: ToastBody) => { setToast({ key: ++seq.current, entry, body }); }, []);
  const closeToast = useCallback(() => { setToast(null); }, []);

  const tokenOf = (id: string): Promise<string | null> => {
    if (!tokens.current.has(id)) return Promise.resolve(null);
    const t = tokens.current.get(id);
    if (t) return Promise.resolve(t);
    return new Promise((res) => { waiting.current.set(id, [...(waiting.current.get(id) ?? []), res]); });
  };

  /** Undo one entry: the top one (↶ and Z) or the given one (a toast's or a slim row's Undo). A refusal (409, 410)
   *  drops the entry and says why; a network failure keeps it and says so. */
  const undo = useCallback(async (id?: string): Promise<void> => {
    const e = id ? entryOf(live.current, id) : topOf(live.current);
    if (!e || busy.current) return;
    busy.current = true;
    setUndoing(true);
    try {
      const token = await tokenOf(e.id);
      if (!token) return;
      const r = await api<UndoReply>(`/api/undo/${token}`, { method: 'POST' });
      drop(e.id);
      move(e.ids, false);
      setToast(null);
      heard.current(e, e.card && e.kind !== 'note' && e.kind !== 'bulk' ? rebuilt(e.card, r.transaction) : null);
      const keys = e.kind === 'note' ? ['review', 'notes', 'transactions', 'label', 'category-rules'] : ['review', 'spending'];
      for (const key of keys) void qc.invalidateQueries({ queryKey: [key] });
    } catch (err) {
      const offline = err instanceof ApiError && err.status === 0;
      if (!offline) drop(e.id);
      setToast({ key: ++seq.current, entry: offline ? e.id : null, body: plainToast(messageOf(err)) });
    } finally {
      busy.current = false;
      setUndoing(false);
    }
  }, [qc]);

  /** A bulk sort's own Undo (its result line) worked: its entry leaves the stack as if this Undo had done it. */
  const forget = useCallback((token: string) => {
    const e = entryWithToken(live.current, token);
    if (!e) return;
    drop(e.id);
    move(e.ids, false);
    heard.current(e, null);
  }, []);

  return { stack, left, toast, undoing, begin, done, fail, say, closeToast, undo, forget };
}
