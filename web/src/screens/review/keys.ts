/** Review focus, Keyboard: when a Review key is left alone. Eager because Z works in the list view too, which never
 *  loads the Focus chunk (engineering choice 4). A pure function of the event, the page and Review's own state. */
export type KeyState = { busy: boolean; menuOpen: boolean };
type KeyLike = Pick<KeyboardEvent, 'key' | 'target' | 'ctrlKey' | 'metaKey' | 'altKey' | 'repeat' | 'defaultPrevented'>;

const TYPING = 'input, textarea, select, [contenteditable]:not([contenteditable="false"])';
// A dialog that is a popover counts only while it is shown (issue #27): the You menu stays in the page, hidden, between
// uses. :is() forgives a browser that doesn't know :popover-open, which would otherwise make the whole query throw.
const OPEN = ':is([role="dialog"]:not([popover]), [role="dialog"]:popover-open), dialog[open], [aria-modal="true"]';
const ACTS_ITSELF = 'button, a, [role^="menuitem"]';

export function ignoreKey(e: KeyLike, s: KeyState): boolean {
  if (e.defaultPrevented || e.repeat || e.ctrlKey || e.metaKey || e.altKey) return true;
  if (s.busy || s.menuOpen) return true;
  const t = e.target instanceof Element ? e.target : null;
  if (t?.closest(TYPING)) return true;
  if (document.querySelector(OPEN)) return true;
  if ((e.key === 'Enter' || e.key === ' ') && t?.closest(ACTS_ITSELF)) return true;
  return false;
}
