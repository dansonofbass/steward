// WEB-3 (release gate 0.1.0, fix 16i): every route names its page. A route that renders a screen and has no title in
// its handle fails here, so the browser tab, history and a screen reader never fall back to a bare "Steward".
import { isValidElement, type ReactElement, type ReactNode } from 'react';
import { Navigate, type RouteObject } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { ToBook } from './book/ToBook';
import { ToProfile } from './book/ToProfile';
import { SECTION_ORDER, SECTION_STEPS } from './lib/profileSections';
import { titleFor, titled, type RouteTitle } from './lib/routeTitles';
import { routes } from './routes';
import { SETTINGS_SLUGS } from './screens/settings/sections';
import { ToSpending } from './screens/spending/ToSpending';

type Leaf = { path: string; title: RouteTitle | undefined; element: ReactNode; parent: boolean };

/** Every route with a path or an index, its full pattern, its title, and whether it has children. */
function leaves(tree: RouteObject[], at = ''): Leaf[] {
  return tree.flatMap((r) => {
    const path = r.path === undefined ? at : r.path.startsWith('/') ? r.path : `${at.replace(/\/$/, '')}/${r.path}`;
    const title = (r.handle as { title?: RouteTitle } | undefined)?.title;
    const own = r.path !== undefined || r.index ? [{ path, title, element: r.element, parent: !!r.children?.length }] : [];
    return [...own, ...leaves(r.children ?? [], path)];
  });
}

const REDIRECTORS: unknown[] = [ToBook, Navigate, ToSpending, ToProfile];
function redirects(el: ReactNode): boolean {
  if (!isValidElement(el)) return false;
  if (REDIRECTORS.includes(el.type)) return true;
  return redirects((el as ReactElement<{ children?: ReactNode }>).props.children);
}

/** The pages that render something of their own, and why a page wouldn't need a name: a redirect, or a layout whose
 *  children each name themselves. */
function untitled(tree: RouteObject[]): string[] {
  return leaves(tree).filter((l) => l.title === undefined && !redirects(l.element) && !l.parent).map((l) => l.path);
}

describe('every route names its page (WEB-3)', () => {
  it('no route that renders a screen is without a title', () => {
    const all = leaves(routes);
    expect(all.length).toBeGreaterThanOrEqual(54);
    expect(untitled(routes)).toEqual([]);
  });

  it('the names are distinct: no two screens share one', () => {
    const fixed = leaves(routes).filter((l) => typeof l.title === 'string' && !l.parent).map((l) => l.title as string);
    const seen = new Map<string, number>();
    for (const t of fixed) seen.set(t, (seen.get(t) ?? 0) + 1);
    // The Plan's layout and its Overview are one page.
    expect([...seen].filter(([, n]) => n > 1).map(([t]) => t)).toEqual([]);
  });

  it("each Settings section and Profile section and step has its own name", () => {
    const at = (path: string) => leaves(routes).find((l) => l.path === path)!.title;
    const settings = SETTINGS_SLUGS.map((section) => titleFor(at('/b/:slug/settings/:section'), { section }));
    expect(new Set(settings).size).toBe(SETTINGS_SLUGS.length);
    expect(settings).not.toContain('Settings');
    const profile = SECTION_ORDER.flatMap((section) => [
      titleFor(at('/b/:slug/profile/:section'), { section }),
      ...SECTION_STEPS[section].map((step) => titleFor(at('/b/:slug/profile/:section/:step'), { section, step })),
    ]);
    expect(new Set(profile).size).toBe(profile.length);
    expect(titleFor(at('/b/:slug/profile/:section/:step'), { section: 'kids', step: 'cover' })).toBe('Kids and college, step 2 of 3');
  });

  it('a title is front-loaded: the page first, the app last', () => {
    expect(titled('Spending')).toBe('Spending · Steward');
    expect(titled('')).toBe('Steward');
  });

  it('catches a route with no title', () => {
    const planted: RouteObject[] = [{ path: '/b/:slug', children: [{ path: 'new', element: <div /> as ReactNode }, { path: 'old', element: <ToBook /> }] }];
    expect(untitled(planted)).toEqual(['/b/:slug/new']);
  });
});
