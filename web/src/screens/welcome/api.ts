// The welcome's server calls (guided setup spec 2, 8). Lazy: only the welcome chunk imports this file.
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { BookSummary } from '../../api/types';
import { queryClient } from '../../queryClient';

/** GET /api/b/{slug}/welcome: what this person's welcome plays and where its steps stand, read live. */
export type WelcomeState = {
  kind: 'first_run' | 'partner' | null;
  seen: boolean;
  inviter: string | null;
  money: { in: boolean; linked: boolean; accounts: number; rows: number };
  waiting: number;
  zone_needed: boolean;
  step: 'money' | 'sort' | 'extras';
};

export const useWelcome = () => useQuery({ queryKey: ['welcome'], queryFn: () => api<WelcomeState>('/api/welcome') });

/** Finish or skip: mark this person's welcome in this book, once, then let /me say it is seen. */
export async function markWelcome(slug: string): Promise<void> {
  await api(`/api/books/${encodeURIComponent(slug)}/welcome`, { method: 'POST' });
  await queryClient.invalidateQueries({ queryKey: ['me'] });
}

/** Look around with a sample household (spec 8): the one this person has, made now if there is none. */
export async function makeSample(): Promise<BookSummary> {
  const r = await api<{ book: BookSummary }>('/api/books/sample', { method: 'POST' });
  return r.book;
}
