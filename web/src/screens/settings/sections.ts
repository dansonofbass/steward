// Settings' sections, without their pages: who sees each, its name and its group. In the first download, because the You
// menu asks whether to offer Settings and the route titles name a section; the pages themselves are in the Settings
// chunk (screens/Settings.tsx), which loads when Settings opens (WEB-19).
import type { Params } from 'react-router-dom';
import type { BookSummary, Me } from '../../api/types';
import {
  S_BANKS_AND_ACCOUNTS, S_BOOK_MEMBERS, S_BOOKS, S_BUSINESS, S_CATEGORY_RULES, S_CHANGES, S_CHAT, S_DISMISSED, S_EXPORT,
  S_IMPORT, S_LOG, S_READY, S_THIS_BOOK, S_WATCHING,
} from '../../lib/copy';

export type Group = 'household' | 'money' | 'features' | 'records';
/** show: listed in Settings. open: reachable by its address though not listed (a viewer's way into the sent log). */
export type SectionRule = {
  slug: string; label: string; group: Group;
  show: (book: BookSummary | null, me: Me | undefined) => boolean; open?: (book: BookSummary | null, step?: string) => boolean;
};

const manager = (b: BookSummary | null) => (b?.role ?? 'manager') === 'manager';
// A Sample has no bank, import, export, members, readiness or chat: nothing leaves it and nothing comes in.
const real = (b: BookSummary | null) => !b?.sample;
const household = (b: BookSummary | null) => (b?.kind ?? 'household') === 'household';
const parent = (b: BookSummary | null) => b?.kind === 'parent';

// A viewer's Settings stays as phase 9 trimmed it (decision 5): in a parent book Watching (where they stop their own
// emails) and the change record, and Books for anyone in two or more books. Their sign-in, devices and appearance are
// under the initials. This book is a manager's (ruling 2). Books also shows to any manager, who can add a book there.
export const SECTION_RULES: SectionRule[] = [
  { slug: 'ready', label: S_READY, group: 'household', show: (b) => manager(b) && household(b) && real(b) },
  { slug: 'members', label: S_BOOK_MEMBERS, group: 'household', show: (b) => manager(b) && real(b) },
  { slug: 'book', label: S_THIS_BOOK, group: 'household', show: manager },
  { slug: 'books', label: S_BOOKS, group: 'household',
    show: (_b, me) => (me?.books.length ?? 0) >= 2 || (me?.books.some((x) => x.role === 'manager') ?? false) },
  { slug: 'banks', label: S_BANKS_AND_ACCOUNTS, group: 'money', show: (b) => manager(b) && real(b) },
  { slug: 'import', label: S_IMPORT, group: 'money', show: (b) => manager(b) && real(b) },
  { slug: 'rules', label: S_CATEGORY_RULES, group: 'money', show: manager },
  { slug: 'business', label: S_BUSINESS, group: 'features', show: (b) => manager(b) && household(b) },
  { slug: 'watching', label: S_WATCHING, group: 'features', show: (b) => parent(b) },
  // Every member reads the sent log (Ask and History link to it); only a manager gets the rest of Chat.
  { slug: 'chat', label: S_CHAT, group: 'features', show: (b) => b !== null && manager(b) && real(b), open: (b, step) => b !== null && real(b) && step === 'sent' },
  { slug: 'log', label: S_LOG, group: 'records', show: manager },
  { slug: 'export', label: S_EXPORT, group: 'records', show: (b) => manager(b) && real(b) },
  { slug: 'changes', label: S_CHANGES, group: 'records', show: (b) => parent(b) },
  { slug: 'dismissed', label: S_DISMISSED, group: 'records', show: (b) => parent(b) && manager(b) },
];

/** Every section's slug, for the axe check's screen list (routes.screens.test.ts). */
export const SETTINGS_SLUGS: string[] = SECTION_RULES.map((s) => s.slug);

/** A section's page title (WEB-3): its name, or Settings for an address that isn't one. */
export const settingsTitle = (p: Params): string => SECTION_RULES.find((s) => s.slug === p.section)?.label ?? 'Settings';

/** Whether the You menu offers "Settings for {book}" (ruling 1): when any section shows for this person in this book. */
export function settingsVisible(book: BookSummary, me: Me | undefined): boolean {
  return SECTION_RULES.some((s) => s.show(book, me));
}
