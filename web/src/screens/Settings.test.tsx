import { screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BookSummary, Me } from '../api/types';
import { renderAt, stubFetch, type Route as Stub } from '../test-utils';
import Settings from './Settings';
import { settingsVisible } from './settings/sections';

afterEach(() => { vi.unstubAllGlobals(); });

const ours: BookSummary = { slug: 'ours', name: 'Ours', kind: 'household', role: 'manager', available: true, reason: null, owners: [], profile: null };
const mom: BookSummary = { ...ours, slug: 'mom', name: 'Mom', kind: 'parent' };
const viewerOf = (b: BookSummary): BookSummary => ({ ...b, role: 'viewer' });
const ROUTES_FOR_BANKS = { '/api/simplefin': { linked: false }, '/api/institutions': { institutions: [] }, '/api/accounts': { accounts: [] } };

// The other routes are empty, so a redirect out of Settings lands somewhere without a warning.
function open(current: BookSummary, books: BookSummary[], path = '/settings', routes: Record<string, Stub> = {}) {
  stubFetch(routes);
  return renderAt(
    <Routes><Route path="/b/:slug/settings/:section?/:step?" element={<Settings />} /><Route path="*" element={null} /></Routes>,
    current, path, books,
  );
}

const list = () => screen.getByRole('navigation', { name: 'Settings list' });
const listed = () => within(list()).getAllByRole('link').map((a) => a.textContent);
const groups = () => within(list()).getAllByRole('heading').map((h) => h.textContent);
const wide = () => vi.stubGlobal('matchMedia', (q: string) => ({ matches: true, media: q, addEventListener: () => {}, removeEventListener: () => {} }));

describe('Settings in four groups', () => {
  it("a manager's household Settings has four groups, and Books though they are in one book (decision 5, ruling 6)", async () => {
    open(ours, [ours]);
    await waitFor(() => expect(listed()).toEqual(['Get Steward ready', 'Book members', 'This book', 'Books', 'Banks and accounts', 'Import', 'Category rules', 'Business', 'Chat', 'Log', 'Export']));
    expect(groups()).toEqual(['Household', 'Money sources', 'Features', 'Records']);
  });

  it('a Sample lists only what works there', async () => {
    const sample: BookSummary = { ...ours, slug: 'sample', name: 'Sample household', sample: true };
    open(sample, [ours, sample]);
    await waitFor(() => expect(listed()).toEqual(['This book', 'Books', 'Category rules', 'Business', 'Log']));
    for (const gone of ['Get Steward ready', 'Book members', 'Banks and accounts', 'Import', 'Export', 'Chat']) {
      expect(within(list()).queryByRole('link', { name: gone })).toBeNull();
    }
  });

  it("a Sample's sent log is not reachable by address", async () => {
    const sample: BookSummary = { ...ours, slug: 'sample', name: 'Sample household', sample: true };
    open(sample, [ours, sample], '/settings/chat/sent', { '/api/chat/sent': { requests: [], people: [], next_offset: null } });
    await screen.findByRole('navigation', { name: 'Settings list' });
    expect(screen.queryByRole('heading', { name: 'Everything sent so far' })).toBeNull();
  });

  it('a manager of a parent book gets Watching, and Change record and Dismissed under Records', async () => {
    open(mom, [mom]);
    await waitFor(() => expect(listed()).toEqual(['Book members', 'This book', 'Books', 'Banks and accounts', 'Import', 'Category rules', 'Watching', 'Chat', 'Log', 'Export', 'Change record', 'Dismissed suggestions']));
  });

  it('Books shows for anyone in two or more books, viewers too (decision 10)', async () => {
    open(viewerOf(ours), [viewerOf(ours), viewerOf(mom)]);
    await waitFor(() => expect(listed()).toEqual(['Books']));
    expect(groups()).toEqual(['Household']);
  });

  it("Books with a step opens that book's details", async () => {
    open(ours, [ours, mom], '/settings/books/mom', { '/api/books/mom/members': { members: [] } });
    expect(await screen.findByRole('heading', { name: 'Mom' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Mom' })).toHaveAttribute('href', '/b/mom');
  });

  it('a viewer of one household book has no sections, only a line saying who changes them (engineering choice 6)', async () => {
    open(viewerOf(ours), [viewerOf(ours)]);
    expect(await screen.findByText('The managers of Ours change its settings.')).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Settings list' })).toBeNull();
  });

  it('a parent-book viewer keeps Watching and the change record (phase 9)', async () => {
    open(viewerOf(mom), [viewerOf(mom)]);
    await waitFor(() => expect(listed()).toEqual(['Watching', 'Change record']));
    expect(groups()).toEqual(['Features', 'Records']);
  });

  it("a viewer who opens a manager's page gets the line, not a page that fails", async () => {
    open(viewerOf(ours), [viewerOf(ours)], '/settings/members');
    expect(await screen.findByText('The managers of Ours change its settings.')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Book members' })).not.toBeInTheDocument();
  });

  it('the title names the book', async () => {
    open(ours, [ours]);
    expect(await screen.findByRole('heading', { level: 1, name: 'Settings for Ours' })).toBeInTheDocument();
  });

  it.each([
    ['/settings/accounts', '/b/ours/accounts'], ['/settings/people', '/b/ours/you/devices'],
    ['/settings/appearance', '/b/ours/you/appearance'], ['/settings/setup', '/b/ours/profile'],
    ['/settings/setup/pay', '/b/ours/profile/you'], ['/settings/profile/children', '/b/ours/profile/kids'],
  ])('an old address %s goes to %s with its query (decision 13)', async (from, to) => {
    const { location } = open(ours, [ours], `${from}?from=email`);
    await waitFor(() => expect(location.current.pathname).toBe(to));
    expect(location.current.search).toBe('?from=email');
  });

  it('on a laptop the groups are one vertical list beside the open section, no tabs', async () => {
    wide();
    open(ours, [ours], '/settings/banks', ROUTES_FOR_BANKS);
    const nav = await screen.findByRole('navigation', { name: 'Settings sections' });
    expect(within(nav).getAllByRole('heading').map((h) => h.textContent)).toEqual(['Household', 'Money sources', 'Features', 'Records']);
    expect(within(nav).getByRole('link', { current: 'page' })).toHaveTextContent('Banks and accounts');
    expect(document.querySelector('.stabs')).toBeNull();
  });

  it('on a laptop a viewer in two books who opens a manager\'s page goes to Books', async () => {
    wide();
    const { location } = open(viewerOf(ours), [viewerOf(ours), viewerOf(mom)], '/settings/members');
    await waitFor(() => expect(location.current.pathname).toBe('/b/ours/settings/books'));
  });

  it("a parent book's old Setup address goes to Profile, which a parent book sends on to its Home", async () => {
    wide();
    const { location } = open(mom, [mom], '/settings/setup');
    await waitFor(() => expect(location.current.pathname).toBe('/b/mom/profile'));
  });

  it('a slug that is only a name on every object is not an old address', async () => {
    const { location } = open(ours, [ours], '/settings/constructor');
    await waitFor(() => expect(listed()).toContain('Book members'));
    expect(location.current.pathname).toBe('/b/ours/settings/constructor');
  });

  it('a viewer with no sections who opens the sent log gets no Settings link back to nothing', async () => {
    open(viewerOf(ours), [viewerOf(ours)], '/settings/chat/sent', {
      '/api/chat/sent': { requests: [], people: [], next_offset: null },
      '/api/chat': { on: true, can_change: false, members: ['JR', 'Rory'], managers: ['JR'] },
    });
    expect(await screen.findByRole('heading', { name: 'Everything sent so far' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Settings' })).toBeNull();
  });

  it('a parent-book viewer on the sent log keeps the Settings link, since they have sections', async () => {
    open(viewerOf(mom), [viewerOf(mom)], '/settings/chat/sent', {
      '/api/chat/sent': { requests: [], people: [], next_offset: null },
      '/api/chat': { on: true, can_change: false, members: ['JR', 'Rory'], managers: ['JR'] },
    });
    expect(await screen.findByRole('heading', { name: 'Everything sent so far' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/b/mom/settings');
  });

  it('on a laptop a viewer with no sections gets the line, not a redirect', async () => {
    wide();
    const { location } = open(viewerOf(ours), [viewerOf(ours)], '/settings/banks');
    expect(await screen.findByText('The managers of Ours change its settings.')).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Settings sections' })).toBeNull();
    expect(location.current.pathname).toBe('/b/ours/settings/banks');
  });

  it("a viewer still reads the book's sent log, and its back link goes to Ask", async () => {
    open(viewerOf(ours), [viewerOf(ours)], '/settings/chat/sent', {
      '/api/chat/sent': { requests: [], people: [], next_offset: null },
      '/api/chat': { on: true, can_change: false, members: ['JR', 'Rory'], managers: ['JR'] },
    });
    expect(await screen.findByRole('heading', { name: 'Everything sent so far' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ask' })).toHaveAttribute('href', '/b/ours/ask');
    expect(screen.queryByRole('link', { name: /Download/ })).not.toBeInTheDocument();
  });
});

describe('whether the You menu offers Settings for the book', () => {
  const me = (...books: BookSummary[]) => ({ books } as Me);
  it('is yes when any section shows for this person in this book', () => {
    expect(settingsVisible(ours, me(ours))).toBe(true);
    expect(settingsVisible(viewerOf(mom), me(viewerOf(mom)))).toBe(true);
    expect(settingsVisible(viewerOf(ours), me(viewerOf(ours), viewerOf(mom)))).toBe(true);
  });
  it('is no for a viewer of one household book', () => {
    expect(settingsVisible(viewerOf(ours), me(viewerOf(ours)))).toBe(false);
    expect(settingsVisible(viewerOf(ours), undefined)).toBe(false);
  });
});
