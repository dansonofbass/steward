import { useQueryClient } from '@tanstack/react-query';
import { Suspense, useEffect, useLayoutEffect, useRef, type ReactNode } from 'react';
import { Navigate, Outlet, useLocation, useParams } from 'react-router-dom';
import { currentBook, setCurrentBook } from '../api/book';
import { AskHost } from '../ask/AskHost';
import { useFlagCount, useMe, useReview } from '../api/hooks';
import type { BookSummary } from '../api/types';
import { TopBar } from '../frame/TopBar';
import { YouMenu } from '../frame/YouMenu';
import { CANT_OPEN_BODY, CANT_OPEN_BOOK, NO_BOOKS, NO_BOOKS_BODY } from '../lib/copy';
import { lazyScreen } from '../lib/lazyScreen';
import { preloadFocusWhenIdle } from '../screens/review/focus/load';
import { EmptyState } from '../ui/EmptyState';
import { Nav, navItems } from '../ui/Nav';
import { BookCtx, bookHref, useBook, useIsHousehold } from './BookContext';
import { BookSwitcher } from './BookSwitcher';
import { pickBook, readLastBook, writeLastBook } from './lastBook';
import { noteProfileOpened, profileOpened } from './profileVisit';
import { welcomeShown } from './welcomeVisit';

// The Sample's ribbon and its Undo are one lazy chunk: only a Sample, or a Sample just removed, loads it.
const SampleFrame = lazyScreen(() => import('./sample/Sample'));

/** The screens of one book (spec 2.4, 2.8). Sets the book before anything below renders, so every query hashes and
 *  fetches under it; cancels the previous book's requests on a switch; sends a household manager who hasn't seen
 *  an unfinished Profile there from the book's Home, once a session (Engineering choice 16, issue #30). The frame is the tabs, the phone's top bar and the
 *  initials at the foot of the rail (decision 4). */
export function BookScope() {
  const { slug = '' } = useParams();
  const { pathname, state } = useLocation();
  const removed = (state as { sampleRemoved?: boolean } | null)?.sampleRemoved === true;
  const atHome = pathname === `/b/${slug}` || pathname === `/b/${slug}/`;
  const me = useMe();   // RequireAuth above has loaded it
  const qc = useQueryClient();
  const books = me.data?.books ?? [];
  const book = books.find((b) => b.slug === slug) ?? null;
  if (book && currentBook() !== book.slug) setCurrentBook(book.slug);
  const prev = useRef<string | null>(null);
  useLayoutEffect(() => {
    if (book) writeLastBook(book.slug);
    const was = prev.current;
    prev.current = slug;
    if (was && was !== slug) void qc.cancelQueries({ predicate: (q) => q.queryHash.startsWith(`["book:${was}"`) });
  }, [slug, book, qc]);
  const review = useReview(book !== null && book.available);
  const flags = useFlagCount(book !== null && book.available && book.kind === 'parent');
  // Review focus P26: the Focus chunk loads when the browser is idle, once something waits for a manager.
  const waiting = book?.role === 'manager' && (review.data?.count ?? 0) > 0;
  useEffect(() => (waiting ? preloadFocusWhenIdle() : undefined), [waiting]);

  if (me.isPending) return <div className="screen" aria-busy="true" />;
  if (!book) {
    const fallback = pickBook(books, readLastBook());
    if (!fallback) return <div className="screen"><EmptyState page title={NO_BOOKS} body={NO_BOOKS_BODY} /></div>;
    return <Navigate to={bookHref(fallback.slug, '/')} replace />;
  }
  // The welcome comes first, once per page load, and holds Profile's first visit until it is done (spec 2.1).
  if (atHome && book.available && book.welcome && !welcomeShown(book.slug)) {
    return <Navigate to={bookHref(book.slug, '/welcome')} replace />;
  }
  if (atHome && book.available && book.kind === 'household' && book.role === 'manager' && book.profile?.seen === false
    && book.profile.finished !== true && !book.welcome && !book.sample && !profileOpened(book.slug)) {
    return <ToProfile slug={book.slug} />;
  }
  const body = book.available
    ? <Outlet key={book.slug} />
    : <div className="screen"><EmptyState page title={CANT_OPEN_BOOK} body={book.reason ?? CANT_OPEN_BODY} /></div>;
  const many = books.length > 1;
  return (
    <BookCtx.Provider value={book}>
      <div className="app">
        <Nav items={navItems(book.slug, book.kind)} count={book.role === 'manager' ? (review.data?.count ?? 0) + (review.data?.business_count ?? 0) : 0} flags={book.kind === 'parent' ? flags.data : undefined}
          home={bookHref(book.slug, '/')} header={many ? <BookSwitcher variant="rail" /> : <span className="nav__book">{book.name}</span>} foot={<YouMenu variant="rail" />} />
        <main className="app__main">
          <TopBar />
          {(book.sample || removed) && <Suspense fallback={null}><SampleFrame ribbon={book.sample === true} undo={removed} /></Suspense>}
          {body}
        </main>
      </div>
      {book.available && <AskHost key={book.slug} />}
    </BookCtx.Provider>
  );
}

/** Home's one trip to Profile this session: noted once it has happened, and Profile says why it opened. */
function ToProfile({ slug }: { slug: string }) {
  useEffect(() => noteProfileOpened(slug), [slug]);
  return <Navigate to={bookHref(slug, '/profile')} replace state={{ fromHome: true }} />;
}

/** Plan and Profile exist only in household books; anywhere else they open the book's Home, or `to` (a parent
 *  book's accounts are in its Inventory). */
export function HouseholdOnly({ children, to = '/' }: { children: ReactNode; to?: string }) {
  const household = useIsHousehold();
  const { slug = '' } = useParams();
  return household ? <>{children}</> : <Navigate to={bookHref(slug, to)} replace />;
}

/** The inventory and its screens exist only in parent books (ruling 32); anywhere else they open the book's Home. */
export function ParentOnly({ children }: { children: ReactNode }) {
  const parent = (useBook()?.kind ?? 'household') === 'parent';
  const { slug = '' } = useParams();
  return parent ? <>{children}</> : <Navigate to={bookHref(slug, '/')} replace />;
}

export type { BookSummary };
