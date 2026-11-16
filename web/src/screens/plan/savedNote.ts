import { dateLabelFromIso } from '../../lib/format';
import { savedWhen } from './levers';
import { planMemory } from './planMemory';

export type SavedNote = { planId: number; at: string; by: string; previous: { name: string | null; saved_at: string } | null };

// Module state (planMemory): the confirmation outlives a trip to another tab and stays until the next change (it never
// fades), or a sign-out.
/** The note only counts for the plan it was saved as; another plan on screen (a refetch, another person's save) hides it. */
export const getSavedNote = (planId?: number | null) => {
  const { note } = planMemory;
  return note && note.planId === planId ? note : null;
};
export function setSavedNote(n: SavedNote | null) { planMemory.note = n; }

export function noteLine(n: SavedNote, now: Date): string {
  const head = `Saved by ${n.by} ${savedWhen(n.at, now)}.`;
  if (!n.previous) return head;
  const when = dateLabelFromIso(n.previous.saved_at, now);
  return n.previous.name
    ? `${head} The previous version, saved by ${n.previous.name} on ${when}, is in Earlier versions.`
    : `${head} The previous version, saved on ${when}, is in Earlier versions.`;
}
