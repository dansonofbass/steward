import { useEffect, useRef } from 'react';
import { Outlet, ScrollRestoration, useLocation, useMatches } from 'react-router-dom';
import { watchSubmits } from '../lib/formErrors';
import { titleFor, titled, type RouteTitle } from '../lib/routeTitles';
import { LiveRegions, useLive } from '../ui/Live';

/** The deepest matched route's name, from its handle (routes.tsx). */
export function usePageName(): string {
  const matches = useMatches();
  for (let i = matches.length - 1; i >= 0; i--) {
    const t = (matches[i].handle as { title?: RouteTitle } | undefined)?.title;
    if (t !== undefined) return titleFor(t, matches[i].params);
  }
  return '';
}

/** Gives a heading focus without scrolling (scroll is ScrollRestoration's), making it focusable if it isn't. */
function focusHeading(h: HTMLElement) {
  if (!h.hasAttribute('tabindex')) h.tabIndex = -1;
  h.focus({ preventScroll: true });
}

const spoken = (el: Element) => (el.textContent ?? '').replace(/\s+/g, ' ').trim();

/** WEB-3: on a page change, the tab says the page's name and focus moves to the page's h1. The name is said politely
 *  only when the h1 doesn't already say it ("November 2026" on Spending), or when focus stays where the page put it.
 *  Focus stays where it is when the new page already placed it (a step's own heading, a tab in the page's own row of
 *  tabs, which stays in the page) or when a sheet is open. A lazy page's h1 can arrive after the page change: it is
 *  awaited until the next page change.
 *
 *  The launch is not a page change: the first page and the redirects that follow it (/ to /b/ours, to /login, to the
 *  welcome) move the address without a person asking, and the browser announces the title itself. The launch ends at
 *  the person's first input (a press, a key or a click, caught on the way down, once), so a page change they cause is
 *  one even when it replaces the address: signing in, accepting an invitation, the welcome's Go home (re-review R-3). */
function PageChange() {
  const name = usePageName();
  const { pathname } = useLocation();
  const live = useLive();
  const launching = useRef(true);
  const seen = useRef(false);
  useEffect(watchSubmits, []);   // WEB-4: a failed submit focuses its first invalid field, on every page
  useEffect(() => {
    const kinds = ['pointerdown', 'keydown', 'click'] as const;
    const stop = () => { for (const k of kinds) document.removeEventListener(k, end, true); };
    const end = () => { launching.current = false; stop(); };
    for (const k of kinds) document.addEventListener(k, end, true);
    return stop;
  }, []);
  useEffect(() => { document.title = titled(name); }, [name]);
  useEffect(() => {
    const initial = !seen.current;
    seen.current = true;
    if (initial || launching.current) return;
    const main = document.querySelector('main') ?? document.getElementById('root') ?? document.body;
    // Placed: a sheet is open, or focus is on something of the new page's (not the phone's top bar, which every page has).
    const placed = () => {
      const at = document.activeElement;
      return document.querySelector('dialog[open]') !== null
        || (at !== null && at !== document.body && main.contains(at) && !at.closest('.topbar'));
    };
    const land = (h1: HTMLElement) => {
      focusHeading(h1);
      if (spoken(h1) !== name) live?.say(name);
    };
    if (placed()) { live?.say(name); return; }
    const h1 = main.querySelector('h1');
    if (h1) { land(h1); return; }
    const watch = new MutationObserver(() => {
      const late = main.querySelector('h1');
      if (!late) return;
      watch.disconnect();
      if (placed()) live?.say(name);
      else land(late);
    });
    watch.observe(main, { childList: true, subtree: true });
    return () => watch.disconnect();
  }, [pathname]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

/** The root of every route: what a page change does whatever the page.
 *  - Scroll (WEB-2): a new page opens at its top, and Back or Forward returns to where that page was. The router keeps
 *    the positions. A change of filters on the same page passes preventScrollReset, so the list stays put.
 *  - Live regions (WEB-7): the page's toast region and polite region are here from the first paint.
 *  - Title and focus (WEB-3): see PageChange. */
export function RouteFrame() {
  return (
    <LiveRegions>
      <ScrollRestoration />
      <PageChange />
      <Outlet />
    </LiveRegions>
  );
}
