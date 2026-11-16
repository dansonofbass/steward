import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api, del } from '../../api/client';
import { useMe, useNotes } from '../../api/hooks';
import type { Txn } from '../../api/types';
import { useCanEdit } from '../../book/BookContext';
import { NOTE_REMOVED, NOTES_NONE, REMOVE } from '../../lib/copy';
import { dateLabelFromIso } from '../../lib/format';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import './notes.css';

const failure = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.');

/** Decision 18: a transaction's notes, "JR, Oct 28: …", newest last; everyone who can see the row reads them, a
 *  manager removes their own. The transaction page and both Review cards. On a card (`onCard`) it says nothing while
 *  loading or with no notes, so a card looks as it did until there is a note to show.
 *  Remove hides the line at once and has an Undo (nothing vanishes unseen): `onRemoved` hands the token to the one
 *  toast of the page it is on (Review's stack and toast on a card, Notes' on the transaction page). */
export function NotesList({ txn, today, onCard = false, onRemoved, home }: {
  txn: Txn; today: Date; onCard?: boolean;
  onRemoved: (token: string, text: string) => void;
  /** Where focus goes when the pressed Remove disappears with its line (a card: the card, or its Note). */
  home?: () => void;
}) {
  const qc = useQueryClient();
  const canEdit = useCanEdit();
  const me = useMe().data?.user.id;
  const q = useNotes(txn.id);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<number | null>(null);   // hidden while its DELETE and the refetch run

  async function refresh() {
    await Promise.all(['transactions', 'review'].map((k) => qc.invalidateQueries({ queryKey: [k] }))
      .concat(qc.invalidateQueries({ queryKey: ['notes', txn.id] })));
  }

  async function remove(id: number) {
    if (removing !== null) return;
    setRemoving(id);
    setError(null);
    home?.();
    try {
      const r = await api<{ undo: string }>(`/api/transactions/${txn.id}/notes/${id}`, del());
      onRemoved(r.undo, NOTE_REMOVED);
      await refresh();
    } catch (err) {
      setError(failure(err));
    } finally {
      setRemoving(null);
    }
  }

  const notes = q.data?.notes.filter((n) => n.id !== removing);
  return (
    <>
      {q.isError ? <Notice tone="error">{q.error.message}</Notice>
        : !notes ? (onCard ? null : <Skeleton lines={1} />)
        : notes.length === 0 ? (onCard ? null : <p className="muted">{NOTES_NONE}</p>) : (
          <ul className="notes__list">
            {notes.map((n) => (
              <li key={n.id} className="txn-note">
                <span><span className="txn-note__meta">{n.author_name}, {dateLabelFromIso(n.created_at, today)}:</span> {n.body}</span>
                {canEdit && n.author_id === me && (
                  <Button variant="quiet" aria-label={`${REMOVE} note from ${dateLabelFromIso(n.created_at, today)}`} disabled={removing !== null} onClick={() => { void remove(n.id); }}>{REMOVE}</Button>
                )}
              </li>
            ))}
          </ul>
        )}
      {error && <Notice tone="error">{error}</Notice>}
    </>
  );
}
