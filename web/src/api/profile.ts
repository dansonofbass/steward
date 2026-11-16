// Profile (src/steward/api/profile.py). Eager: Home's line and BookScope read it; the Profile chunk does the rest.
import { useQuery, type QueryClient } from '@tanstack/react-query';
import type { SectionKey, SectionStatus } from '../lib/profileSections';
import { setQueryDataIfStillIn } from '../queryClient';
import { currentBook } from './book';
import { api, json, patch, put } from './client';
import type { Names } from './household';
import type { UserBrief } from './types';

export type SectionState = {
  key: SectionKey; status: SectionStatus; minutes: number; resume_step: string | null;
  by_id: number | null; by: string | null; at: string | null; missing: string | null;
};
export type ProfileMarks = { seen: boolean; confirmed: boolean; later_until: string | null };
export type Role = 'jr' | 'spouse';
export type ProfilePerson = { user_id: number; display_name: string };
export type ProfileState = {
  sections: SectionState[]; done: number; total: number; next: SectionKey | null; finished: boolean;
  me: ProfileMarks & { user_id: number; role: Role | null };
  names: Names; people: { jr: ProfilePerson | null; spouse: ProfilePerson | null };
};
export type Answer = 'done' | 'skipped' | 'doesnt_apply';
export type Undoable = { undo: string | null };

export const useProfile = (enabled = true) => useQuery({ queryKey: ['profile'], queryFn: () => api<ProfileState>('/api/profile'), enabled });
export const answerSection = (key: SectionKey, status: Answer) => api<ProfileState>(`/api/profile/sections/${key}`, json({ status }));
export const setResume = (key: SectionKey, step: string | null) => api<ProfileState>(`/api/profile/sections/${key}/resume`, put({ step }));
export const markSeen = () => api<ProfileState>('/api/profile/seen', json({}));
export const confirmMine = () => api<ProfileState>('/api/profile/confirm', json({}));
export const setLater = (later: boolean) => api<ProfileState & Undoable>('/api/profile/later', json({ later }));
/** One Undo for several writes: tokens are URL-safe base64, so "." joins them; undoing runs last write first. */
export const chainTokens = (...tokens: (string | null)[]): string | null => {
  const real = tokens.filter((t): t is string => !!t);
  return real.length ? real.join('.') : null;
};
export async function undoToken(token: string): Promise<unknown> {
  let last: unknown;
  for (const t of token.split('.').reverse()) last = await api<unknown>(`/api/undo/${t}`, { method: 'POST' });
  return last;
}
export const renameMe = (display_name: string) => api<{ user: UserBrief }>('/api/auth/me', patch({ display_name }));

/** Inside the person's Later window (P5): Home's line stays away until it ends. */
export const inLater = (m: Pick<ProfileMarks, 'later_until'> | null | undefined, now: Date = new Date()): boolean =>
  !!m?.later_until && new Date(m.later_until) > now;

/** After an answer or a mark: keep the server's answer, then refetch everything that shows the profile or names. */
export async function refreshProfile(qc: QueryClient, request?: Promise<ProfileState>): Promise<void> {
  const book = currentBook();   // read before the await: the reply belongs to the book that asked
  const state = await request;
  if (state) setQueryDataIfStillIn<ProfileState>(qc, book, ['profile'], () => state);
  await Promise.all(['profile', 'me', 'users', 'plan-setup', 'plan'].map((k) => qc.invalidateQueries({ queryKey: [k] })));
}
