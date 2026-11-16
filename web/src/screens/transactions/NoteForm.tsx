import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { getLabel, saveLabel } from '../../api/labels';
import { undoToken } from '../../api/profile';
import type { LabelView, Txn } from '../../api/types';
import { money } from '../../lib/format';
import { composing } from '../../lib/ime';
import { Button } from '../../ui/Button';
import { Field } from '../../ui/Field';
import { Notice } from '../../ui/Notice';
import { useSheetSaved } from '../../ui/Sheet';
import { UndoToast } from '../../ui/UndoToast';
import * as C from './noteCopy';

const fill = (s: string, v: Record<string, string | number>) => s.replace(/\{(\w+)\}/g, (_, k: string) => String(v[k]));
const failure = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.');

/** "Also the 11 PayPal $13.99 ones" (copy table): the amount only for a generic payee (P32); null with no other row. */
export function alsoLabel(v: LabelView): string | null {
  const r = v.reach;
  if (!r || r.others === 0) return null;
  const amount = r.amount_cents !== null ? money(Math.abs(r.amount_cents)) : null;
  if (r.others === 1) return amount ? fill(C.ALSO_ONE_GENERIC, { payee: r.payee, amount }) : fill(C.ALSO_ONE, { payee: r.payee });
  return amount ? fill(C.ALSO_GENERIC, { n: r.others, payee: r.payee, amount }) : fill(C.ALSO_PLAIN, { n: r.others, payee: r.payee });
}

/** The note form (polish round, item 5; its own lazy chunk): a note and a name, "Also…" for the rows like it, and "And
 *  future ones" for the rule. Name starts as the row's name, or the rule's; future starts ticked only when a rule
 *  already carries a label (Engineering choice 4). Also starts ticked only with a name or that label, so a quick note
 *  stays on its own row; a name typed later ticks it until the person touches it. One Save, one Undo; the form stays,
 *  cleared, with its toast. */
export default function NoteForm({ txn, onCancel, onSaved, autoFocus = false }: {
  txn: Txn; onCancel?: () => void;
  /** Review (both views) and the transaction page: the save goes on the page's one toast instead of this form's own. */
  onSaved?: (s: { token: string; text: string }) => void;
  /** Review focus, N: focus lands in Note in the same commit as the form shows (so a slow chunk can't lose it). */
  autoFocus?: boolean;
}) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['label', txn.id], queryFn: () => getLabel(txn.id) });
  const v = q.data;
  const [note, setNote] = useState('');
  const [name, setName] = useState<string | null>(null);      // null: not touched, so the prefill shows
  const [also, setAlso] = useState<boolean | null>(null);     // null: not touched, so a name or the rule decides
  const [future, setFuture] = useState<boolean | null>(null); // null: the rule decides
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ text: string; token: string } | null>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const markSaved = useSheetSaved(formRef);   // this form only: the detail form below keeps its own unsaved text
  const labelled = !!v?.rule && (v.rule.nickname !== null || v.rule.note !== null);
  const nameText = name ?? v?.nickname ?? v?.rule?.nickname ?? '';
  const futureOn = future ?? labelled;
  const alsoOn = also ?? (labelled || nameText.trim() !== '');
  const alsoText = v ? alsoLabel(v) : null;
  const noteBox = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => { if (autoFocus) noteBox.current?.focus(); }, [autoFocus]);
  /** Review focus P27: Enter saves from Note or Name, wherever the form is used; Shift+Enter is a new line; Esc cancels. */
  function keys(e: KeyboardEvent<HTMLFormElement>) {
    if (e.key === 'Escape' && onCancel) { e.stopPropagation(); onCancel(); return; }
    const t = e.target as HTMLElement;
    const field = t.tagName === 'TEXTAREA' || (t.tagName === 'INPUT' && (t as HTMLInputElement).type !== 'checkbox');
    if (e.key === 'Enter' && !e.shiftKey && !composing(e) && field) {
      e.preventDefault();
      e.currentTarget.requestSubmit();
    }
  }

  async function refresh() {
    await Promise.all(['notes', 'transactions', 'review', 'label', 'category-rules', 'setasides'].map((k) => qc.invalidateQueries({ queryKey: [k] })));
  }
  async function save(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    const n = note.trim();
    const nm = nameText.trim();
    if (!n && !nm) { setError(C.NOTHING); return; }
    setBusy(true);
    setError(null);
    try {
      const r = await saveLabel(txn.id, { note: n || null, nickname: nm || null, also: alsoText !== null && alsoOn, future: !!v?.reach && futureOn });
      setNote('');
      setName(null);
      setAlso(null);
      setFuture(null);
      const text = r.rows === 1 ? C.SAVED : fill(C.SAVED_ON, { n: r.rows });
      if (onSaved) onSaved({ token: r.undo, text }); else setToast({ text, token: r.undo });
      await refresh();
      // In a sheet: Name now shows the saved name (read back by refresh), so closing asks nothing about it.
      markSaved();
    } catch (err) {
      setError(failure(err));
    } finally {
      setBusy(false);
    }
  }
  async function undo() {
    const t = toast?.token;
    setToast(null);
    try { if (t) await undoToken(t); } catch (err) { setError(failure(err)); }
    await refresh();
  }

  return (
    <form ref={formRef} className="note-form stack stack--tight" data-testid="note-form" aria-busy={q.isPending} onSubmit={(e) => void save(e)}
      onKeyDown={keys}>
      <Field label={C.NOTE}>
        <textarea ref={noteBox} autoFocus={autoFocus} value={note} rows={2} maxLength={1000} onChange={(e) => { setNote(e.target.value); setError(null); }} />
      </Field>
      <Field label={C.NAME}>
        <input value={nameText} maxLength={40} onChange={(e) => { setName(e.target.value); setError(null); }} />
      </Field>
      {alsoText && (
        <label className="check-row"><input type="checkbox" checked={alsoOn} onChange={(e) => setAlso(e.target.checked)} /><span>{alsoText}</span></label>
      )}
      {v?.reach && (
        <label className="check-row"><input type="checkbox" checked={futureOn} onChange={(e) => setFuture(e.target.checked)} /><span>{C.FUTURE}</span></label>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      <div className="row-actions">
        <Button type="submit" variant="quiet" busy={busy}>{C.SAVE}</Button>
        {onCancel && <Button variant="quiet" onClick={onCancel}>{C.CANCEL}</Button>}
      </div>
      {toast && <UndoToast text={toast.text} onUndo={() => void undo()} onClose={() => setToast(null)} />}
    </form>
  );
}
