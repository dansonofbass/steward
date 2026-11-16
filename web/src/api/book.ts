// Which book the app is in, and how a book API path is spelled (spec 2.4). The /b/:slug screens set the book before
// they render (book/BookScope.tsx); api() and the query cache read it. Screens keep writing '/api/accounts'.
const TOP_LEVEL = ['/api/auth', '/api/users', '/api/books', '/api/invites', '/api/health', '/api/setup', '/api/install'];
let current: string | null = null;

export const currentBook = (): string | null => current;

const listeners = new Set<(from: string | null, to: string | null) => void>();

/** Called after the open book changes. The query cache uses it to cancel in-flight book queries. */
export function onBookChange(fn: (from: string | null, to: string | null) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function setCurrentBook(slug: string | null): void {
  const from = current;
  current = slug;
  if (from !== slug) listeners.forEach((fn) => fn(from, slug));
}

/** '/api/accounts' → '/api/b/<book>/accounts'. Person and directory routes, and paths already naming a book, pass through. */
export function resolveApiPath(path: string, book: string | null = current): string {
  if (!path.startsWith('/api/') || path.startsWith('/api/b/')) return path;
  if (TOP_LEVEL.some((p) => path === p || path.startsWith(`${p}/`) || path.startsWith(`${p}?`))) return path;
  if (!book) throw new Error(`No book is open for ${path}.`);
  return `/api/b/${encodeURIComponent(book)}${path.slice(4)}`;
}
