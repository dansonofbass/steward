import { createContext, useContext, useEffect } from 'react';
import { useLocation } from 'react-router-dom';

// Issue #29: a page for one item (an account, a set-aside, a trip) titles the tab with the item's name once it has
// loaded, "Joint checking · Steward", so two such pages can be told apart in the tab switcher and history. Until the
// item loads, the route's own noun stands (lib/routeTitles.ts). RouteFrame holds the store and sets document.title.

/** The name, with the address it is for, so a name left by the page before never titles the next one. */
export type ItemName = { path: string; name: string } | null;

/** A store, not state in RouteFrame: setting it re-renders only what titles the page, not every page under the frame. */
export function itemNameStore() {
  let value: ItemName = null;
  const listeners = new Set<() => void>();
  return {
    get: () => value,
    set: (next: ItemName) => { value = next; for (const l of listeners) l(); },
    subscribe: (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; },
  };
}
export type ItemNames = ReturnType<typeof itemNameStore>;
export const ItemNameCtx = createContext<ItemNames | null>(null);

// A masked account number ("••6789", "xx6789", "...6789", "#6789"), and the mask itself.
const MASKED = /[\s(]*(?:[•●∙*#…]+|\.{2,}|\b[xX]+(?=\d))\s?\d{2,}\)?/g;
// A number of three or more digits, with its separators and currency sign ("6789", "$1,500", "2026").
const NUMBER = /[$€£]?\d(?:[\d,.]*\d)?/g;

// The names of US retirement and college plans, which are kinds of account, not an account's numbers: 401(k), 403(b),
// 457(b) and 529. They are held aside while the numbers go, then put back.
const PLAN = /\b(?:40[13]|457)\s?\([a-z]\)|(?<![•●∙*#…x.\d])\b529\b/gi;

/** The name as a page title may show it. A title goes into the browser's history and, with sync on, to the browser's
 *  maker, so it never carries an item's numbers: no masked account number, no run of three or more digits. A plan's
 *  own name (401(k), 529) stays. What is left of the name (it may be nothing) is tidied of the brackets and dashes the
 *  numbers stood in. */
export function titleName(name: string): string {
  const plans: string[] = [];
  return name
    .replace(PLAN, (p) => `\u0000${String.fromCharCode(65 + plans.push(p) - 1)}\u0000`)
    .replace(MASKED, ' ')
    .replace(NUMBER, (n) => (n.replace(/\D/g, '').length >= 3 ? ' ' : n))
    .replace(/\(\s*\)|\[\s*\]/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/^[\s\-–—·,:;#/]+|[\s\-–—·,:;#/]+$/g, '')
    .replace(/\u0000([A-Z])\u0000/g, (_, i: string) => plans[i.charCodeAt(0) - 65] ?? '');
}

/** Titles the page with `name` while it is set (without its numbers, titleName); nothing outside RouteFrame (a
 *  screen's own test). */
export function useItemTitle(given: string | null | undefined) {
  const store = useContext(ItemNameCtx);
  const { pathname } = useLocation();
  const name = given ? titleName(given) : '';
  useEffect(() => {
    if (!store || !name) return;
    const mine = { path: pathname, name };
    store.set(mine);
    return () => { if (store.get() === mine) store.set(null); };
  }, [store, pathname, name]);
}
