// The Ask about this panel's state (phase 13 spec, P3): one per book, in memory, gone on reload. Eager and tiny; the
// panel itself is the lazy chunk (ask/panel.ts), which reads this with useAskState.
import { useSyncExternalStore } from 'react';
import type { AboutIn, Surface } from './about';

export type AskState = {
  /** The panel has been opened in this book, so its chunk is mounted, and stays mounted while closed (P3). */
  mounted: boolean;
  open: boolean;
  about: AboutIn | null;
  surface: Surface | null;
  /** The button that opened it, for focus when it closes (P27). */
  opener: HTMLElement | null;
  /** Counts opens from a button: on each, the panel resumes the same thing or starts again. */
  seq: number;
};
const INITIAL: AskState = { mounted: false, open: false, about: null, surface: null, opener: null, seq: 0 };
let state = INITIAL;
const subs = new Set<() => void>();
const set = (next: AskState) => { state = next; subs.forEach((f) => { f(); }); };
const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f); }; };

export function openAsk(about: AboutIn, surface: Surface, opener: HTMLElement | null): void {
  set({ mounted: true, open: true, about, surface, opener, seq: state.seq + 1 });
}
export function closeAsk(): void {
  if (state.open) set({ ...state, open: false });
}
/** The toast's Open: the same conversation, the same thing. */
export function reopenAsk(): void {
  if (state.mounted && !state.open) set({ ...state, open: true });
}
/** Switching books drops the panel (P3). */
export function resetAsk(): void {
  if (state !== INITIAL) set(INITIAL);
}
export const askState = (): AskState => state;
export const useAskState = (): AskState => useSyncExternalStore(subscribe, askState, askState);
