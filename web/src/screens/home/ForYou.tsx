import { useQueryClient } from '@tanstack/react-query';
import { Suspense, useRef, useState } from 'react';
import { currentBook } from '../../api/book';
import { dismissEvent, type HomeData } from '../../api/home';
import { useReview, useTaxNotice } from '../../api/hooks';
import { inLater, setLater, undoToken, useProfile, type ProfileState } from '../../api/profile';
import { useBook, useCanEdit } from '../../book/BookContext';
import { Link } from '../../book/links';
import { backgroundLine } from '../../lib/background';
import { LazyBackgroundLine } from './lazyMoments';
import { collapse } from '../../lib/collapse';
import { DISMISS, LATER_TOAST, LINE_LATER } from '../../lib/copy';
import { setQueryDataIfStillIn } from '../../queryClient';
import type { ReviewQueue } from '../../api/types';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { UndoToast } from '../../ui/UndoToast';
import { failure } from '../settings/shared';
import * as C from './copy';
import { forYouRows, SHOWN, type Row } from './forYouRows';

type Toast = { text: string; token: string | null; key: string; refresh: string[] };
const fill = (s: string, vars: Record<string, string | number>) => s.replace(/\{(\w+)\}/g, (_, k: string) => String(vars[k]));

/** For you (Home spec, section 2): one card for every to-do. Its rows come from /api/home (not refetched on focus, so
 *  a row whose source clears elsewhere is gone on the next visit, not while you look), the Review count and the
 *  background line from /api/review (the nav's query), and tax and Profile after ready. A row that leaves folds away,
 *  then the toast says so, with Undo (nothing vanishes unseen). */
export function ForYou({ data, ready }: { data: HomeData; ready: boolean }) {
  const canEdit = useCanEdit();
  const book = useBook();
  const qc = useQueryClient();
  const review = useReview();
  const tax = useTaxNotice(ready);                                   // P16: after ready
  const profile = useProfile(ready && !inLater(book?.profile));      // today's rule: after ready, never in the Later week
  const [open, setOpen] = useState(false);
  const [gone, setGone] = useState<ReadonlySet<string>>(new Set());
  const [toast, setToast] = useState<Toast | null>(null);
  const [error, setError] = useState<string | null>(null);
  const head = useRef<HTMLHeadingElement>(null);
  const els = useRef(new Map<string, HTMLLIElement>());
  // The Review row keeps the first count this visit sees: it must not vanish unseen when the nav's query refetches.
  const firstReview = useRef<ReviewQueue | undefined>(undefined);
  if (review.data && !firstReview.current) firstReview.current = review.data;
  const rows = forYouRows({ data, canEdit, review: firstReview.current, tax: tax.data, profile: profile.data }).filter((r) => !gone.has(r.key));
  const bgText = review.data?.background ? backgroundLine(review.data.background) : null;
  const shown = open ? rows : rows.slice(0, SHOWN);

  /** The row folds away (200 ms, instant under reduced motion); if it held the focus, the heading takes it. */
  function leave(key: string) {
    const el = els.current.get(key) ?? null;
    const focused = el !== null && el.contains(document.activeElement);
    collapse(el, () => {
      setGone((g) => new Set(g).add(key));
      if (focused) head.current?.focus();
    });
  }

  async function dismiss(row: Row, id: number) {
    setError(null);
    try {
      const { undo } = await dismissEvent(id);
      leave(row.key);
      setToast({ text: C.DISMISSED, token: undo, key: row.key, refresh: ['home', 'events'] });
      void qc.invalidateQueries({ queryKey: ['events'] });
    } catch (e) {
      setError(failure(e));
    }
  }

  async function later(row: Row) {
    setError(null);
    try {
      const b = currentBook();
      const state = await setLater(true);
      leave(row.key);
      setQueryDataIfStillIn<ProfileState>(qc, b, ['profile'], () => state);
      setToast({ text: LATER_TOAST, token: state.undo, key: row.key, refresh: ['profile', 'me'] });
      await qc.invalidateQueries({ queryKey: ['me'] });
    } catch (e) {
      setError(failure(e));
    }
  }

  async function undo() {
    if (!toast) return;
    setError(null);
    try {
      if (toast.token) await undoToken(toast.token);
    } catch (e) {
      setError(failure(e));                                 // the toast stays, so Undo does too (exact restore or 409)
      return;
    }
    const { key, refresh } = toast;
    setToast(null);
    setGone((g) => { const next = new Set(g); next.delete(key); return next; });
    await Promise.all(refresh.map((k) => qc.invalidateQueries({ queryKey: [k] })));
  }

  return (
    <section className="card foryou" aria-labelledby="foryou-h" data-testid="for-you">
      <h2 id="foryou-h" ref={head} tabIndex={-1}>{C.FOR_YOU}</h2>
      {rows.length === 0 ? <p className="muted">{C.NOTHING_NEEDS_YOU}</p> : (
        <ul className="foryou__list">
          {shown.map((r) => (
            <li key={r.key} className="foryou__row" data-testid={r.key === 'profile' ? 'profile-line' : 'foryou-row'}
              ref={(el) => { if (el) els.current.set(r.key, el); else els.current.delete(r.key); }}>
              <span className={`foryou__dot${r.amber ? ' is-amber' : ''}`} aria-hidden="true" />
              {r.action && r.dismiss === undefined && !r.later ? (
                <Link className="foryou__main" to={r.action.to}>
                  <span className="foryou__text">{r.text}</span>
                  <span className="foryou__act">{r.action.label}</span>
                </Link>
              ) : (
                <>
                  <span className="foryou__text">{r.text}</span>
                  {(r.action || r.dismiss !== undefined || r.later) && (
                    <span className="foryou__acts">
                      {r.action && <Link className="foryou__act" to={r.action.to}>{r.action.label}</Link>}
                      {r.dismiss !== undefined && (
                        <Button variant="quiet" aria-label={`${DISMISS}: ${r.text}`} onClick={() => void dismiss(r, r.dismiss!)}>{DISMISS}</Button>
                      )}
                      {r.later && <Button variant="quiet" onClick={() => void later(r)}>{LINE_LATER}</Button>}
                    </span>
                  )}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {!open && rows.length > SHOWN && <Button variant="quiet" onClick={() => setOpen(true)}>{fill(C.MORE_N, { n: rows.length - SHOWN })}</Button>}
      {review.data?.background && (
        <Suspense fallback={bgText && <p className="foryou__foot muted bg-line" data-testid="background-line">{bgText}</p>}>
          <LazyBackgroundLine bg={review.data.background} className="foryou__foot muted" testId="background-line" />
        </Suspense>
      )}
      {error && <Notice tone="error"><p>{error}</p></Notice>}
      {toast && <UndoToast text={toast.text} onUndo={() => void undo()} onClose={() => { setToast(null); setError(null); }} />}
    </section>
  );
}
