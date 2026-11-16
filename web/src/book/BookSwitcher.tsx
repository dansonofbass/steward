import { Check, ChevronsUpDown, Settings as SettingsIcon } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useMe } from '../api/hooks';
import type { BookSummary } from '../api/types';
import { ALL_BOOKS, BOOKS, HOUSEHOLD_KIND, MANAGER_ROLE, PARENT_KIND, SAMPLE_META, SWITCH_BOOK, VIEWER_ROLE } from '../lib/copy';
import { Sheet } from '../ui/Sheet';
import { bookHref, useBook } from './BookContext';
import { switchTarget } from './switch';
import './BookSwitcher.css';

const kindWord = (b: BookSummary) => (b.kind === 'household' ? HOUSEHOLD_KIND : PARENT_KIND);
const roleWord = (b: BookSummary) => (b.role === 'manager' ? MANAGER_ROLE : VIEWER_ROLE);

function BookList({ books, current, onPick }: { books: BookSummary[]; current: BookSummary; onPick: () => void }) {
  const { pathname } = useLocation();
  return (
    <ul className="books__list">
      {books.map((b) => {
        const here = b.slug === current.slug;
        return (
          <li key={b.slug}>
            <Link className={`books__row${here ? ' is-current' : ''}`} to={switchTarget(pathname, current.slug, b)}
              aria-current={here ? 'true' : undefined} onClick={onPick}>
              <span className="books__text">
                <span className="books__name">{b.name}</span>
                {b.sample
                  ? <span className="books__meta books__tag">{SAMPLE_META}</span>
                  : <span className="books__meta">{kindWord(b)} · {roleWord(b)}</span>}
              </span>
              {here && <Check className="books__check" size={20} aria-hidden="true" />}
            </Link>
          </li>
        );
      })}
      <li>
        <Link className="books__row books__manage" to={bookHref(current.slug, '/settings/books')} onClick={onPick}>
          <SettingsIcon size={20} aria-hidden="true" /><span>{ALL_BOOKS}</span>
        </Link>
      </li>
    </ul>
  );
}

/** Design notes: at the top of the desktop rail (a list under the button) and as a bar at the top of each phone
 *  screen (the bottom sheet). Only for people with two or more books. */
export function BookSwitcher({ variant }: { variant: 'rail' | 'bar' }) {
  const book = useBook();
  const me = useMe();
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const listId = useId();
  const books = me.data?.books ?? [];

  useEffect(() => {
    if (!open || variant !== 'rail') return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setOpen(false); button.current?.focus(); } };
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!panel.current?.contains(t) && !button.current?.contains(t)) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDown);
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('mousedown', onDown); };
  }, [open, variant]);

  if (!book || books.length < 2) return null;
  const close = () => setOpen(false);
  const meta = book.sample ? SAMPLE_META : kindWord(book);
  return (
    <div className={`books books--${variant}`}>
      <button ref={button} type="button" className="books__button" aria-expanded={open}
        aria-controls={variant === 'rail' && open ? listId : undefined} aria-label={`${SWITCH_BOOK}: ${variant === 'rail' ? `${book.name}, ${meta}` : book.name}`}
        onClick={() => setOpen((o) => !o)}>
        <span className="books__text">
          <span className="books__name">{book.name}</span>
          {/* The rail shows the kind under the name, so the button's name says it too (WCAG 2.5.3, T7). */}
          {variant === 'rail' && <> <span className={`books__meta${book.sample ? ' books__tag' : ''}`}>{meta}</span></>}
        </span>
        <ChevronsUpDown size={20} aria-hidden="true" />
      </button>
      {variant === 'rail' && open && (
        <div ref={panel} id={listId} className="books__panel"><BookList books={books} current={book} onPick={close} /></div>
      )}
      {variant === 'bar' && (
        <Sheet open={open} onClose={close} title={BOOKS}><BookList books={books} current={book} onPick={close} /></Sheet>
      )}
    </div>
  );
}
