import { ChevronLeft } from 'lucide-react';
import { Link as RouterLink } from 'react-router-dom';
import { useMe, useMembers } from '../../api/hooks';
import type { InvitedRow, Member } from '../../api/types';
import { bookHref, useBook } from '../../book/BookContext';
import { Link, Navigate } from '../../book/links';
import { HOUSEHOLD_KIND, KIND, MANAGERS, NONE, OPEN_BOOK, PARENT_KIND, S_BOOKS, VIEWERS } from '../../lib/copy';
import { Card } from '../../ui/Card';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { failure } from './shared';

// A manager's list also has the people invited who have not joined; they have no name yet, so they aren't listed.
const joined = (m: Member | InvitedRow): m is Member => m.user_id !== null;

function Names({ label, names }: { label: string; names: string[] }) {
  return (
    <div className="line">
      <div className="line__main"><span>{label}</span><span className="small muted">{names.length ? names.join(', ') : NONE}</span></div>
    </div>
  );
}

/** Settings, Books, one book: its kind and who manages and views it, read without switching to it (decision 10). Open
 *  switches to it; the book already open has nothing to open. */
export default function BookDetails({ slug }: { slug: string }) {
  const me = useMe();
  const current = useBook();
  const book = me.data?.books.find((b) => b.slug === slug);
  const members = useMembers(slug);
  if (me.data && !book) return <Navigate to="/settings/books" replace />;
  const people = members.data?.members.filter(joined) ?? [];
  const named = (role: Member['role']) => people.filter((m) => m.role === role).map((m) => m.display_name);
  return (
    <section className="spage" aria-labelledby="book-details-h">
      <Link className="link" to="/settings/books"><ChevronLeft className="i" size={20} aria-hidden="true" />{S_BOOKS}</Link>
      <h2 id="book-details-h">{book?.name}</h2>
      {book && (
        <Card className="lines">
          <div className="line">
            <div className="line__main"><span>{KIND}</span><span className="small muted">{book.kind === 'household' ? HOUSEHOLD_KIND : PARENT_KIND}</span></div>
          </div>
          {members.data && <><Names label={MANAGERS} names={named('manager')} /><Names label={VIEWERS} names={named('viewer')} /></>}
        </Card>
      )}
      {members.isPending && <Card><Skeleton lines={2} /></Card>}
      {members.isError && <Notice tone="error">{failure(members.error)}</Notice>}
      {book && book.slug !== current?.slug && (
        <div><RouterLink className="btn btn--primary" to={bookHref(book.slug, '/')}><span className="btn__content"><span>{OPEN_BOOK.replace('{book}', book.name)}</span></span></RouterLink></div>
      )}
    </section>
  );
}
