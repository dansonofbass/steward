import type { Txn } from '../../api/types';

/** Review focus, The list (P20, P21): the visit's rows in a fixed order, each with what happened to it. An acted card
 *  stays in its place as a slim row until Review is left or the view switches; nothing is ever reordered, and new rows
 *  are appended at the end. `back` counts the times Undo grew a row back (its card shows "Undone."). */
export type Outcome =
  | { kind: 'waiting' }
  | { kind: 'sorted'; category: string; n: number; entry: string }
  | { kind: 'matched'; category: string; entry: string }
  | { kind: 'snoozed'; until: string; entry: string }
  | { kind: 'ignored'; entry: string }
  | { kind: 'bulk'; category: string; entry: string }
  | { kind: 'elsewhere' };
export type VisitRow = { id: number; txn: Txn; outcome: Outcome; back: number };
export type Visit = readonly VisitRow[];
export type VisitAction =
  | { type: 'sync'; queue: readonly Txn[] }
  | { type: 'acted'; id: number; outcome: Outcome; matched?: { ids: readonly number[]; category: string } }
  | { type: 'bulk'; ids: readonly number[]; category: string; entry: string }
  | { type: 'restore'; entry: string; card?: Txn }
  | { type: 'clear' };

const WAITING: Outcome = { kind: 'waiting' };
const ELSEWHERE: Outcome = { kind: 'elsewhere' };
const entryIn = (o: Outcome): string | null => ('entry' in o ? o.entry : null);

/** The entry a slim row's Undo undoes: none for a matched row (its parent's Undo restores it) or one sorted elsewhere. */
export const undoOf = (o: Outcome): string | null => (o.kind === 'matched' || o.kind === 'elsewhere' ? null : entryIn(o));

export function visitReducer(rows: Visit, a: VisitAction): Visit {
  switch (a.type) {
    case 'sync': {
      const byId = new Map(a.queue.map((t) => [t.id, t]));
      let changed = false;
      const kept = rows.map((r) => {
        const t = byId.get(r.id);
        if (r.outcome.kind === 'elsewhere' && t) { changed = true; return { ...r, txn: t, outcome: WAITING }; }
        if (r.outcome.kind !== 'waiting') return r;
        if (!t) { changed = true; return { ...r, outcome: ELSEWHERE }; }
        if (t === r.txn) return r;
        changed = true;
        return { ...r, txn: t };
      });
      const known = new Set(rows.map((r) => r.id));
      const added = a.queue.filter((t) => !known.has(t.id)).map((t) => ({ id: t.id, txn: t, outcome: WAITING, back: 0 }));
      return changed || added.length ? [...kept, ...added] : rows;
    }
    case 'acted': {
      const matched = new Set(a.matched?.ids ?? []);
      const entry = entryIn(a.outcome);
      return rows.map((r) => {
        if (r.id === a.id) return { ...r, outcome: a.outcome };
        if (a.matched && entry && matched.has(r.id) && r.outcome.kind === 'waiting') {
          return { ...r, outcome: { kind: 'matched', category: a.matched.category, entry } };
        }
        return r;
      });
    }
    case 'bulk': {
      const ids = new Set(a.ids);
      return rows.map((r) => (ids.has(r.id) && r.outcome.kind === 'waiting'
        ? { ...r, outcome: { kind: 'bulk', category: a.category, entry: a.entry } } : r));
    }
    case 'restore': {
      // Undo: every row of the entry grows back. An entry made in the other view has no row here: its card, when
      // given, comes back at the end (nothing is ever inserted).
      let hit = false;
      const next = rows.map((r) => {
        if (entryIn(r.outcome) !== a.entry) return r;
        hit = true;
        return { ...r, outcome: WAITING, back: r.back + 1 };
      });
      if (hit || !a.card || rows.some((r) => r.id === a.card!.id)) return next;
      return [...next, { id: a.card.id, txn: a.card, outcome: WAITING, back: 1 }];
    }
    case 'clear':
      return [];
  }
}
