import { useQueryClient } from '@tanstack/react-query';
import { Suspense, useRef, useState, type FormEvent } from 'react';
import { api, json } from '../../api/client';
import { undoToken } from '../../api/profile';
import type { Note, Txn } from '../../api/types';
import { useCanEdit, useIsHousehold } from '../../book/BookContext';
import { ADD_NOTE, NOTE_LABEL, NOTES } from '../../lib/copy';
import { lazyScreen } from '../../lib/lazyScreen';
import { Button } from '../../ui/Button';
import { Field } from '../../ui/Field';
import { Notice } from '../../ui/Notice';
import { UndoToast } from '../../ui/UndoToast';
import { NotesList } from './NotesList';

const NoteForm = lazyScreen(() => import('./NoteForm'));

/** Decision 18: a transaction's notes (NotesList), with the add box for a manager; viewers read.
 *  In a household book the add box is the note form (polish round, item 5): a note and a name that can reach the rows
 *  like it and future ones; a parent book keeps the plain box. One toast for the page: a save from the form and a
 *  Remove both hand their Undo here, and the newer replaces the older, so the Undo on screen is always the last action's. */
export function Notes({ txn, today }: { txn: Txn; today: Date }) {
  const qc = useQueryClient();
  const canEdit = useCanEdit();
  const household = useIsHousehold();
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ token: string; text: string } | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const say = (token: string, text: string) => { setToast({ token, text }); };

  async function refresh() {
    await Promise.all([qc.invalidateQueries({ queryKey: ['notes', txn.id] }), qc.invalidateQueries({ queryKey: ['transactions'] }), qc.invalidateQueries({ queryKey: ['review'] })]);
  }

  // A save's Undo can reach names and rules too (NoteForm's own refresh), so those are refreshed with the notes.
  async function undo() {
    const t = toast?.token;
    setToast(null);
    try { if (t) await undoToken(t); } catch (err) { setError(err instanceof Error ? err.message : 'Something went wrong.'); }
    await Promise.all([refresh(), ...['label', 'category-rules', 'setasides'].map((k) => qc.invalidateQueries({ queryKey: [k] }))]);
  }

  async function add(e: FormEvent) {
    e.preventDefault();
    const words = body.trim();
    if (busy || !words) return;
    setBusy(true);
    setError(null);
    try {
      await api<Note>(`/api/transactions/${txn.id}/notes`, json({ body: words }));
      setBody('');
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="notes stack stack--tight" aria-labelledby={`notes-${txn.id}`}>
      <h3 ref={heading} id={`notes-${txn.id}`} className="eyebrow" tabIndex={-1}>{NOTES}</h3>
      <NotesList txn={txn} today={today} onRemoved={say} home={() => { heading.current?.focus(); }} />
      {error && <Notice tone="error">{error}</Notice>}
      {canEdit && household && <Suspense fallback={null}><NoteForm txn={txn} onSaved={(r) => { say(r.token, r.text); }} /></Suspense>}
      {canEdit && !household && (
        <form className="txn-note__form" onSubmit={add}>
          <Field label={NOTE_LABEL}>
            <textarea value={body} rows={2} maxLength={1000} onChange={(e) => { setBody(e.target.value); }} />
          </Field>
          <Button type="submit" variant="quiet" busy={busy} disabled={!body.trim()}>{ADD_NOTE}</Button>
        </form>
      )}
      {toast && <UndoToast key={toast.token} text={toast.text} onUndo={() => void undo()} onClose={() => { setToast(null); }} />}
    </section>
  );
}
