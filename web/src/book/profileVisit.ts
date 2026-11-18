/** Which books' Home has already opened Profile this browser session (issue #30). BookScope sends a household manager
 *  whose profile is unseen and unfinished from Home to Profile at most once a session, so choosing Home again, or
 *  opening the book's address, goes Home. Kept in sessionStorage, so a reload in the same tab remembers and a new tab
 *  starts fresh; where storage is blocked, for this page load only. Sign-out forgets it, so the next person to sign in
 *  in this tab gets their own visit. */
const KEY = 'steward.profileOpened';
const opened = new Set<string>();

function stored(): string[] {
  try {
    const v: unknown = JSON.parse(sessionStorage.getItem(KEY) ?? '[]');
    return Array.isArray(v) ? v.filter((s): s is string => typeof s === 'string') : [];
  } catch {
    return [];
  }
}

export const profileOpened = (slug: string): boolean => opened.has(slug) || stored().includes(slug);

export function noteProfileOpened(slug: string): void {
  opened.add(slug);
  try { sessionStorage.setItem(KEY, JSON.stringify([...new Set([...stored(), slug])])); } catch { /* this page load only */ }
}

/** Start a fresh session: at sign-out, and in tests. */
export function forgetProfileOpened(): void {
  opened.clear();
  try { sessionStorage.removeItem(KEY); } catch { /* nothing kept */ }
}
