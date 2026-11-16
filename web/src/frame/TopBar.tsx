import { useMe } from '../api/hooks';
import { useBook } from '../book/BookContext';
import { BookSwitcher } from '../book/BookSwitcher';
import { YouMenu } from './YouMenu';
import './TopBar.css';

/** The phone's top bar (decision 4): the book switcher, or the book's name for a person in one book, and the
 *  person's initials. From 900 px the rail carries both. */
export function TopBar() {
  const book = useBook();
  const me = useMe();
  if (!book) return null;
  const many = (me.data?.books.length ?? 0) > 1;
  return (
    <header className="topbar">
      {many ? <BookSwitcher variant="bar" /> : <span className="topbar__book">{book.name}</span>}
      <YouMenu variant="bar" />
    </header>
  );
}
