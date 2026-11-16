import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useBook } from '../../book/BookContext';
import { Navigate } from '../../book/links';
import { noteWelcomeShown } from '../../book/welcomeVisit';
import { Skeleton } from '../../ui/Skeleton';
import { useWelcome } from './api';
import { FirstRun } from './FirstRun';
import { PartnerWelcome } from './PartnerWelcome';

/** The welcome (guided setup spec 2): the first run, or a partner's welcome (Task 9). Opening it counts as this
 *  visit's welcome, so leaving it for Home doesn't send the person back (BookScope). A person with no welcome, or one
 *  already seen, goes Home unless it was asked for again (Help's "See the welcome again") or is the planting, which
 *  follows the mark (the address says so, not the state). */
export default function Welcome() {
  const book = useBook();
  const welcome = useWelcome();
  const [params] = useSearchParams();
  const again = params.get('again') === '1';
  const slug = book?.slug;
  useEffect(() => { if (slug) noteWelcomeShown(slug); }, [slug]);
  const s = welcome.data;
  if (!s) return <div className="screen">{welcome.isError ? <p role="alert">{welcome.error.message}</p> : <Skeleton />}</div>;
  if (s.kind === null || (s.seen && !again && params.get('step') !== 'planted')) return <Navigate to="/" replace />;
  if (s.kind === 'partner') return <PartnerWelcome state={s} again={again} />;
  return <FirstRun state={s} again={again} />;
}
