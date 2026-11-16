import type { BookSummary } from '../api/types';
import { bookHref } from './BookContext';

// Screens, and Settings sections, that only a household has. Setup is Profile's old address.
const HOUSEHOLD_ONLY = new Set(['plan', 'setup', 'cashflow', 'spending', 'profile', 'accounts', 'taxes', 'business']);
const PARENT_ONLY = new Set(['inventory']);
// Settings sections a Sample does not have (nothing leaves a Sample, and it takes no imports or members).
const SAMPLE_SECTIONS = new Set(['ready', 'members', 'banks', 'import', 'export', 'chat']);
const PARENT_SECTIONS = new Set(['changes', 'dismissed']);
// Sections Settings opens only for a manager (This book too, ruling 2), so a viewer isn't sent to one.
const MANAGER_SECTIONS = new Set(['banks', 'import', 'profile', 'dismissed', 'members', 'log', 'book', 'chat', 'business']);

/** Where choosing `to` goes from `pathname` in book `from`: the same screen there, its Settings when a viewer can't
 *  use that section or the book has none, or its Home when it has no such screen. Search parameters are dropped. */
export function switchTarget(pathname: string, from: string, to: BookSummary): string {
  const prefix = bookHref(from, '/');
  const rest = pathname === prefix || pathname.startsWith(`${prefix}/`) ? pathname.slice(prefix.length) : '';
  const parts = rest.split('/').filter(Boolean);
  const [first = '', second = ''] = parts;
  const home = bookHref(to.slug, '/');
  const settings = bookHref(to.slug, '/settings');
  if (to.kind !== 'household' && first === 'accounts') return bookHref(to.slug, '/inventory');   // a parent's accounts are there
  if (to.kind !== 'household' && (HOUSEHOLD_ONLY.has(first) || (first === 'settings' && HOUSEHOLD_ONLY.has(second)))) return home;
  if (to.kind !== 'parent' && PARENT_ONLY.has(first)) return home;
  if (to.kind !== 'parent' && first === 'settings' && PARENT_SECTIONS.has(second)) return settings;
  if (to.role !== 'manager' && first === 'settings' && MANAGER_SECTIONS.has(second)) return settings;
  if (to.sample && first === 'settings' && SAMPLE_SECTIONS.has(second)) return settings;
  // An item, or an account, belongs to one book: open the other book's list.
  if ((first === 'inventory' || first === 'accounts') && parts.length > 1) return bookHref(to.slug, `/${first}`);
  return bookHref(to.slug, parts.length ? `/${parts.join('/')}` : '/');
}
