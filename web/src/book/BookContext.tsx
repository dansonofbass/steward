import { createContext, useCallback, useContext } from 'react';
import { currentBook } from '../api/book';
import type { BookSummary } from '../api/types';

export const BookCtx = createContext<BookSummary | null>(null);

export const useBook = (): BookSummary | null => useContext(BookCtx);

export function bookHref(slug: string, to: string): string {
  return `/b/${encodeURIComponent(slug)}${to === '/' ? '' : to}`;
}

/** In-app paths are written as before ('/settings/banks'); this puts one in the open book. Outside a book (unit
 *  tests) it uses the book the API client has, "ours" by default. */
export function useBookTo(): (to: string) => string {
  const slug = useBook()?.slug ?? currentBook() ?? 'ours';
  return useCallback((to: string) => bookHref(slug, to), [slug]);
}

export const useCanEdit = (): boolean => (useBook()?.role ?? 'manager') === 'manager';
export const useIsHousehold = (): boolean => (useBook()?.kind ?? 'household') === 'household';
