import type { Txn } from '../../api/types';
import type { ReviewView } from '../../lib/reviewPrefs';

/** Review focus, Undo (P14): one entry per action this visit, newest last; both views share it. The server keeps one
 *  token per action (POST /undo/{token}); the stack only orders them. `token` is null while the action is in flight. */
export type Kind = 'sort' | 'snooze' | 'ignore' | 'bulk' | 'note';
export type Entry = {
  id: string;
  token: string | null;
  kind: Kind;
  /** The card and the rows its sort spread to (result.ids); a bulk sort's rows. */
  ids: number[];
  /** The card as it showed, with its "N like it" count, so Undo brings it back as it was (P15). */
  card: Txn | null;
  view: ReviewView;
};
export const STACK_MAX = 50;
export type Stack = readonly Entry[];
export type StackAction =
  | { type: 'push'; entry: Entry }
  | { type: 'settle'; id: string; token: string; ids?: number[] }
  | { type: 'drop'; id: string }
  | { type: 'clear' };

export function stackReducer(s: Stack, a: StackAction): Stack {
  switch (a.type) {
    case 'push': {
      const next = [...s, a.entry];
      return next.length > STACK_MAX ? next.slice(next.length - STACK_MAX) : next;
    }
    case 'settle': return s.map((e) => (e.id === a.id ? { ...e, token: a.token, ids: a.ids ?? e.ids } : e));
    case 'drop': return s.filter((e) => e.id !== a.id);
    case 'clear': return [];
  }
}

export const topOf = (s: Stack): Entry | null => s[s.length - 1] ?? null;
export const entryOf = (s: Stack, id: string): Entry | null => s.find((e) => e.id === id) ?? null;
export const entryWithToken = (s: Stack, token: string): Entry | null => s.find((e) => e.token === token) ?? null;
