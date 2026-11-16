import { isValidElement, type ReactElement, type ReactNode } from 'react';
import { Navigate, type RouteObject } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { REDIRECTS, SCREENS } from '../e2e/screens';
import { ToBook } from './book/ToBook';
import { ToProfile } from './book/ToProfile';
import { SECTION_ORDER, SECTION_STEPS } from './lib/profileSections';
import { routes } from './routes';
import { SETTINGS_SLUGS } from './screens/settings/sections';
import { ToSpending } from './screens/spending/ToSpending';

// T7 (docs/CLAIMS.md): the axe check (e2e/axe.spec.ts) visits every screen. Each route pattern in routes.tsx, with its
// parents' paths joined on, is a screen the check visits or a redirect, which renders nothing of its own to check.

type Pattern = { path: string; element: ReactNode };

/** Every route's full pattern, each child's path joined to its parent's. An index route is its parent's path, and a
 *  pathless layout route passes its parent's path to its children. */
function patterns(tree: RouteObject[], parent = ''): Pattern[] {
  return tree.flatMap((r) => {
    const path = r.path === undefined ? parent : r.path.startsWith('/') ? r.path : `${parent.replace(/\/$/, '')}/${r.path}`;
    const own = r.path !== undefined || r.index ? [{ path, element: r.element }] : [];
    return [...own, ...patterns(r.children ?? [], path)];
  });
}

/** The patterns that no screen and no redirect covers. */
function unvisited(tree: RouteObject[], screens: readonly string[], redirects: readonly string[]): string[] {
  const covered = new Set([...screens, ...redirects]);
  return [...new Set(patterns(tree).map((p) => p.path))].filter((p) => !covered.has(p));
}

const REDIRECTORS: unknown[] = [ToBook, Navigate, ToSpending, ToProfile];
/** Whether the element is a redirect, or wraps one as its only child (cashflow sits inside HouseholdOnly). */
function redirects(el: ReactNode): boolean {
  if (!isValidElement(el)) return false;
  if (REDIRECTORS.includes(el.type)) return true;
  return redirects((el as ReactElement<{ children?: ReactNode }>).props.children);
}

/** The Settings sections and Profile sections (and each guided flow's first step) that no screen opens. Each sits
 *  behind one route pattern (/settings/:section, /profile/:section(/:step)), so the route check alone can't see one. */
function unvisitedSections(urls: readonly string[], settings: readonly string[], profile: readonly string[],
                           steps: Readonly<Record<string, readonly string[]>>): string[] {
  const opened = (tail: string) => urls.some((u) => u.split('?')[0].endsWith(tail));
  const wanted = [
    ...settings.map((slug) => `/settings/${slug}`),
    ...profile.flatMap((key) => [`/profile/${key}`, `/profile/${key}/${steps[key][0]}`]),
  ];
  return wanted.filter((tail) => !opened(tail));
}

describe('the screens the axe check visits', () => {
  it('every route in routes.tsx has a screen the axe check visits', () => {
    const all = patterns(routes);
    expect(all.length).toBeGreaterThanOrEqual(54);
    expect(unvisited(routes, SCREENS.map((s) => s.route), REDIRECTS)).toEqual([]);
    // A redirect renders only its target, which has its own screen; a real screen can't be listed as one.
    for (const path of REDIRECTS) {
      const found = all.filter((p) => p.path === path);
      expect(found.length, path).toBeGreaterThan(0);
      for (const p of found) expect(redirects(p.element), `${path} is not a redirect`).toBe(true);
    }
    // And no screen covers a pattern that routes.tsx no longer has.
    const live = new Set(all.map((p) => p.path));
    expect(SCREENS.map((s) => s.route).filter((r) => !live.has(r))).toEqual([]);
  });

  it('the check notices a route with no screen', () => {
    const tree: RouteObject[] = [
      { path: '/login' },
      { children: [{ path: '/b/:slug', children: [{ index: true }, { path: 'spending' }, { path: 'plan', children: [{ index: true }, { path: 'try' }] }] }] },
    ];
    const screens = ['/login', '/b/:slug', '/b/:slug/plan', '/b/:slug/plan/try'];
    expect(unvisited(tree, screens, [])).toEqual(['/b/:slug/spending']);
    expect(unvisited(tree, screens, ['/b/:slug/spending'])).toEqual([]);
  });

  it('every Settings section and Profile section has a screen the axe check visits', () => {
    expect(SETTINGS_SLUGS.length).toBeGreaterThanOrEqual(14);
    expect(unvisitedSections(SCREENS.map((s) => s.url), SETTINGS_SLUGS, SECTION_ORDER, SECTION_STEPS)).toEqual([]);
  });

  it('the check notices a section with no screen', () => {
    const urls = ['/b/ours/settings/ready', '/b/ours/profile/you', '/b/ours/profile/you/you'];
    const steps = { you: ['you', 'partner'], kids: ['kids'] };
    expect(unvisitedSections(urls, ['ready', 'secrets'], ['you'], steps)).toEqual(['/settings/secrets']);
    expect(unvisitedSections(urls, ['ready'], ['you', 'kids'], steps)).toEqual(['/profile/kids', '/profile/kids/kids']);
    expect(unvisitedSections(urls, ['ready'], ['you'], steps)).toEqual([]);
  });

  it('every screen has a name of its own', () => {
    const names = SCREENS.map((s) => s.name);
    expect(names.filter((n, i) => names.indexOf(n) !== i)).toEqual([]);
  });
});
