import { ChevronRight } from 'lucide-react';
import { useMe } from '../../api/hooks';
import { bookHref, useBook } from '../../book/BookContext';
import { Link } from '../../book/links';
import { HELP, S_READY } from '../../lib/copy';

const SEE_WELCOME = 'See the welcome again';

/** You › Help (guided setup spec 7.5): play this book's welcome again, and, for someone who manages the install, the
 *  way back to Get Steward ready. The replay marks nothing (?again=1). */
export default function Help() {
  const book = useBook();
  const me = useMe();
  const installBook = me.data?.books.find((b) => b.install && b.role === 'manager');
  return (
    <div className="screen">
      <h1>{HELP}</h1>
      <div className="card slist">
        {!book?.sample && <Link to="/welcome?again=1">{SEE_WELCOME}<ChevronRight size={20} aria-hidden="true" /></Link>}
        {installBook && <Link to={bookHref(installBook.slug, '/settings/ready')}>{S_READY}<ChevronRight size={20} aria-hidden="true" /></Link>}
      </div>
    </div>
  );
}
