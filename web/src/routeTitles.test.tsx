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

// Issue #29: a page for one item (an address with an :id, a :category) titles the tab with the item's name once it has
// loaded, by calling useItemTitle (frame/itemTitle.ts). Each such route in a book is listed here with the module that
// calls it, or in NOT_TITLED with the reason it keeps its fixed noun. A new item route in neither list fails.
const SOURCES: Record<string, string> = import.meta.glob<string>(
  ['/src/screens/**/*.tsx', '!/src/screens/**/*.test.tsx'], { query: '?raw', import: 'default', eager: true });

const TITLED: Record<string, string> = {
  '/b/:slug/spending/setasides/:id': '/src/screens/spending/setasides/SetAside.tsx',
  '/b/:slug/spending/reimbursements/trips/:id': '/src/screens/reimburse/Trip.tsx',
  '/b/:slug/spending/:category': '/src/screens/spending/Category.tsx',
  '/b/:slug/accounts/:id': '/src/screens/accounts/AccountPage.tsx',
  '/b/:slug/inventory/:id': '/src/screens/inventory/ItemPage.tsx',
  '/b/:slug/inventory/:id/edit': '/src/screens/inventory/ItemForm.tsx',
};

/** Item routes that keep their fixed noun, and why. `never`: a module that must not call useItemTitle. */
const NOT_TITLED: Record<string, { reason: string; never?: string }> = {
  '/b/:slug/inventory/:id/attach': { reason: "Attach a file: the page's h1 doesn't name the item either" },
  '/b/:slug/look-into/:id': {
    reason: "privacy: a flag's title describes a money worry, and a page title goes into the browser's history and sync",
    never: '/src/screens/watching/FlagPage.tsx',
  },
  '/b/:slug/profile/:section': { reason: 'a Profile section, named by its section (T.profileSection)' },
  '/b/:slug/profile/:section/:step': { reason: 'a Profile step, named by its section and step (T.profileStep)' },
  '/b/:slug/settings/:section': { reason: 'a Settings section, named by settingsTitle; Book details names the book (below)' },
  '/b/:slug/settings/:section/:step': { reason: 'a step of a Settings section, named by settingsTitle' },
};

/** Modules of a section that is about one item: Book details names the book. */
const ALSO_TITLED = ['/src/screens/settings/BookDetails.tsx'];

/** Routes in a book whose address names one thing (a parameter past the book's :slug), that render a page. */
function itemRoutes(tree: RouteObject[]): string[] {
  return leaves(tree)
    .filter((l) => l.path.startsWith('/b/:slug/') && /\/:/.test(l.path.slice('/b/:slug'.length)) && !redirects(l.element) && !l.parent)
    .map((l) => l.path);
}
const unlisted = (tree: RouteObject[]) => itemRoutes(tree).filter((p) => !(p in TITLED) && !(p in NOT_TITLED));
const callsItemTitle = (file: string) => /\buseItemTitle\(/.test(SOURCES[file] ?? '');

describe("a page for one item is titled by the item's name (issue #29)", () => {
  it('every item route is listed: titled by its item, or with the reason it keeps its noun', () => {
    expect(itemRoutes(routes).length).toBeGreaterThanOrEqual(12);
    expect(unlisted(routes)).toEqual([]);
    // No stale entry: each listed route still exists.
    const all = itemRoutes(routes);
    expect([...Object.keys(TITLED), ...Object.keys(NOT_TITLED)].filter((p) => !all.includes(p))).toEqual([]);
  });

  it("each titled route's screen calls useItemTitle", () => {
    for (const file of [...Object.values(TITLED), ...ALSO_TITLED]) {
      expect(SOURCES[file], `${file} exists`).toBeDefined();
      expect(callsItemTitle(file), `${file} calls useItemTitle`).toBe(true);
    }
  });

  it('a page that must keep its noun never calls useItemTitle', () => {
    const never = Object.values(NOT_TITLED).flatMap((n) => (n.never ? [n.never] : []));
    expect(never).toContain('/src/screens/watching/FlagPage.tsx');
    for (const file of never) {
      expect(SOURCES[file], `${file} exists`).toBeDefined();
      expect(callsItemTitle(file), `${file} calls useItemTitle`).toBe(false);
    }
  });

  it('catches a new item route that is in neither list', () => {
    const planted: RouteObject[] = [{ path: '/b/:slug', children: [
      { path: 'things', element: <div />, handle: { title: 'Things' } },
      { path: 'things/:id', element: <div />, handle: { title: 'Thing' } },
      { path: 'old/:id', element: <ToBook /> },
    ] }];
    expect(unlisted(planted)).toEqual(['/b/:slug/things/:id']);
  });
});
