// The Sample's frame (guided setup spec 8, 11): a ribbon on every screen of a Sample book, and the Undo that follows
// Remove. Lazy: BookScope loads both from this one chunk, and only a Sample or a just-removed Sample needs it.
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, ApiError } from '../../api/client';
import { freshMe, useMe } from '../../api/hooks';
import type { BookSummary } from '../../api/types';
import { Button } from '../../ui/Button';
import { UndoToast } from '../../ui/UndoToast';
import { bookHref } from '../BookContext';
import { REMOVE, REMOVE_SAMPLE, SAMPLE, SAMPLE_REMOVED, YOUR_BOOK } from './copy';
import './sample.css';

const AGAIN = "That didn't finish. Try again.";
const words = (e: unknown) => (e instanceof ApiError ? e.message : AGAIN);

/** The household: the install's book, else the first household-kind book that is not a Sample, else the first that is not. */
function householdOf(books: BookSummary[]): BookSummary | null {
  const real = books.filter((b) => !b.sample);
  return real.find((b) => b.install) ?? real.find((b) => b.kind === 'household') ?? real[0] ?? null;
}

export function SampleRibbon() {
  const me = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const home = householdOf(me.data?.books ?? []);
  const to = !home ? '/' : bookHref(home.slug, home.welcome === 'first_run' ? '/welcome' : '/');
  async function remove() {
    setBusy(true);
    setError('');
    try {
      const r = await api<{ removed: boolean; household: string }>('/api/books/sample', { method: 'DELETE' });
      // Leave first: once /me no longer lists the Sample, BookScope would send this address to another book and drop the state.
      navigate(bookHref(r.household || home?.slug || '', '/'), { state: { sampleRemoved: true } });
      void qc.invalidateQueries({ queryKey: ['me'] });
    } catch (e) {
      setError(words(e));
      setBusy(false);
    }
  }
  return (
    <div className="sample-ribbon" role="note">
      <strong className="sample-ribbon__name">{SAMPLE}</strong>
      <span className="sample-ribbon__acts">
        <Link className="link" to={to}>{YOUR_BOOK}</Link>
        <Button variant="quiet" busy={busy} disabled={busy} aria-label={REMOVE_SAMPLE} onClick={() => void remove()}>{REMOVE}</Button>
      </span>
      {error && <span className="sample-ribbon__error" role="alert">{error}</span>}
    </div>
  );
}

/** BookScope's one lazy part: the ribbon in a Sample, the Undo after Remove. */
export default function SampleFrame({ ribbon, undo }: { ribbon: boolean; undo: boolean }) {
  return <>{ribbon && <SampleRibbon />}{undo && <SampleUndo />}</>;
}

/** "Sample removed · Undo", once per arrival; a refused Undo shows the server's words and no Undo. */
export function SampleUndo() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [text, setText] = useState<string | null>(SAMPLE_REMOVED);
  const [refused, setRefused] = useState(false);
  if (text === null) return null;
  async function undo() {
    try {
      const r = await api<{ book: BookSummary }>('/api/books/sample/restore', { method: 'POST' });
      await freshMe(qc);
      setText(null);
      navigate(bookHref(r.book.slug, '/'));
    } catch (e) {
      setText(words(e));
      setRefused(true);
    }
  }
  return <UndoToast key={refused ? 'refused' : 'undo'} text={text} onUndo={refused ? undefined : () => void undo()} onClose={() => setText(null)} />;
}
