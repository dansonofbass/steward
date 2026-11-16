import { hashKey, QueryClient, type QueryKey } from '@tanstack/react-query';
import { ApiError } from './api/client';
import { currentBook, onBookChange } from './api/book';

/** Keys that belong to the person, not a book. Every other key is cached per book, so switching books never shows
 *  the other book's numbers and switching back is instant. */
export const PERSON_KEYS = new Set(['me', 'users', 'passkeys', 'sessions', 'books']);

export function bookKeyHash(key: QueryKey): string {
  return PERSON_KEYS.has(String(key[0])) ? hashKey(key) : hashKey([`book:${currentBook() ?? ''}`, ...key]);
}

/** Store an answer that arrived after an await, unless the person has switched books meanwhile: the key is hashed
 *  with the book open when the write happens, so a late answer would land in the other book's entry. */
export function setQueryDataIfStillIn<T>(qc: QueryClient, book: string | null, key: QueryKey, updater: (old: T | undefined) => T | undefined): boolean {
  if (currentBook() !== book) return false;
  qc.setQueryData<T>(key, updater);
  return true;
}

export function makeQueryClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: {
        retry: (failureCount, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && failureCount < 1,
        refetchOnWindowFocus: true,
        staleTime: 10_000,
        queryKeyHashFn: bookKeyHash,
      },
    },
  });
  // A queryFn resolves the open book on every attempt, so a retry firing after a switch would fetch the new book's
  // data into the old book's entry. Cancel book queries on a switch; that also ends their pending retry.
  onBookChange(() => {
    void qc.cancelQueries({ predicate: (q) => !PERSON_KEYS.has(String(q.queryKey[0])) });
  });
  return qc;
}

export const queryClient = makeQueryClient();
