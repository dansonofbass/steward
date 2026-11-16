// The first-use tip's mark (Ask about this P23): per person on this device, under steward-ask-tour:{user id}, as the
// Review view key is. Every access is in try/catch; when storage throws, the tip shows at most once per page load.
const key = (userId: number) => `steward-ask-tour:${userId}`;
let shownThisLoad = false;

export function tourDue(userId: number): boolean {
  try {
    return localStorage.getItem(key(userId)) !== 'done';
  } catch {
    return !shownThisLoad;
  }
}

export function tourShown(): void {
  shownThisLoad = true;
}

export function tourDone(userId: number): void {
  shownThisLoad = true;
  try {
    localStorage.setItem(key(userId), 'done');
  } catch { /* the page-load flag keeps it to once */ }
}

/** Tests only. */
export function resetTourLoad(): void {
  shownThisLoad = false;
}
