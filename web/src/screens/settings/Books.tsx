import { ChevronRight, Plus } from 'lucide-react';
import { Suspense, useEffect, useState } from 'react';
import { useMe } from '../../api/hooks';
import { useBook } from '../../book/BookContext';
import { Link } from '../../book/links';
import { ADD_A_BOOK, HOUSEHOLD_KIND, PARENT_KIND, S_BOOKS, THIS_BOOK_LINE, YOU_MANAGE, YOU_VIEW } from '../../lib/copy';
import { lazyScreen } from '../../lib/lazyScreen';
import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import './members.css';

// The add-a-book sheet is a lazy chunk (shared with Get Steward ready and the first run); Books preloads it for a manager.
const AddBookSheet = lazyScreen(() => import('./AddBookSheet'));

/** Settings, Books: every book the person is in. A row opens that book's details here, without switching to it
 *  (decision 10). Only someone who manages a book can add one; the server refuses everyone else. */
export default function Books() {
  const me = useMe();
  const current = useBook();
  const [adding, setAdding] = useState(false);
  const books = me.data?.books ?? [];
  const manages = books.some((b) => b.role === 'manager');
  useEffect(() => { if (manages) void AddBookSheet.preload(); }, [manages]);   // ready before Add a book is pressed
  return (
    <>
      <section className="spage" aria-labelledby="books-h">
        <h2 id="books-h">{S_BOOKS}</h2>
        <Card className="lines">
          {books.map((b) => (
            <Link key={b.slug} className="line line--link" to={`/settings/books/${encodeURIComponent(b.slug)}`}>
              <div className="line__main">
                <span>{b.name}</span>
                <span className="small muted">
                  {b.slug === current?.slug && `${THIS_BOOK_LINE} · `}{b.kind === 'household' ? HOUSEHOLD_KIND : PARENT_KIND} · {b.role === 'manager' ? YOU_MANAGE : YOU_VIEW}
                </span>
              </div>
              <ChevronRight size={20} aria-hidden="true" />
            </Link>
          ))}
        </Card>
        {manages && <div><Button icon={Plus} onClick={() => setAdding(true)}>{ADD_A_BOOK}</Button></div>}
      </section>
      {adding && <Suspense fallback={null}><AddBookSheet onClose={() => setAdding(false)} /></Suspense>}
    </>
  );
}
