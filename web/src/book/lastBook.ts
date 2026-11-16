import type { BookSummary } from '../api/types';

const KEY = 'steward.lastBook';

export function readLastBook(): string | null {
  try { return localStorage.getItem(KEY); } catch { return null; }
}

export function writeLastBook(slug: string): void {
  try { localStorage.setItem(KEY, slug); } catch { /* a private window: the fallback is fine */ }
}

/** Spec 2.4 and ruling 4: the last-used book on this device, or ours, or the first. */
export function pickBook(books: BookSummary[], last: string | null): BookSummary | null {
  return books.find((b) => b.slug === last) ?? books.find((b) => b.slug === 'ours') ?? books[0] ?? null;
}
