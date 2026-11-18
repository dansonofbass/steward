import { Navigate, useLocation } from 'react-router-dom';
import { useMe } from '../api/hooks';
import { NO_BOOKS, NO_BOOKS_BODY } from '../lib/copy';
import { EmptyState } from '../ui/EmptyState';
import { bookHref } from './BookContext';
import { pickBook, readLastBook } from './lastBook';

/** An address without a book (a bookmark from before books): the same screen in the last-used book (spec 2.4). */
export function ToBook() {
  const me = useMe();
  const loc = useLocation();
  if (me.isPending) return <div className="screen" aria-busy="true" />;
  const book = pickBook(me.data?.books ?? [], readLastBook());
  if (!book) return <div className="screen"><EmptyState page title={NO_BOOKS} body={NO_BOOKS_BODY} /></div>;
  return <Navigate to={`${bookHref(book.slug, loc.pathname)}${loc.search}`} replace />;
}
