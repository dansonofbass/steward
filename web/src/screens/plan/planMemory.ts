// What the Plan pages keep in this tab between visits: the unsaved lever moves (usePlanDraft) and the saved note
// (savedNote). Type imports only, so the frame's sign-out can clear it without pulling the Plan chunk into the first
// bundle.
import type { Draft } from './levers';
import type { SavedNote } from './savedNote';

export const planMemory: { kept: { key: string; draft: Draft } | null; note: SavedNote | null } = { kept: null, note: null };

/** Forgets the kept moves and the saved note. Sign-out calls it, so the next person to sign in on this tab sees neither. */
export function clearKeptDraft(): void {
  planMemory.kept = null;
  planMemory.note = null;
}
