import { useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { api, patch } from '../../api/client';
import type { BookSummary } from '../../api/types';
import { useBook, useCanEdit } from '../../book/BookContext';
import { NAME, S_THIS_BOOK, SAVE, SAVED } from '../../lib/copy';
import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import { Field } from '../../ui/Field';
import { Notice } from '../../ui/Notice';
import { failure } from './shared';

function BookName({ book }: { book: BookSummary }) {
  const canEdit = useCanEdit();
  const qc = useQueryClient();
  const [name, setName] = useState(book.name);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  if (!canEdit) return <Card><p>{book.name}</p></Card>;

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await api(`/api/books/${encodeURIComponent(book.slug)}`, patch({ name: name.trim() }));
      await qc.invalidateQueries({ queryKey: ['me'] });
      setSaved(true);
    } catch (err) {
      setError(failure(err));
    }
    setBusy(false);
  }
  return (
    <form className="card sheet-form" onSubmit={save}>
      <Field label={NAME} error={error}>
        <input value={name} maxLength={60} onChange={(e) => { setName(e.target.value); setSaved(false); }} />
      </Field>
      <div className="row-actions"><Button type="submit" busy={busy} disabled={!name.trim() || name.trim() === book.name}>{SAVE}</Button></div>
      {saved && <Notice>{SAVED}</Notice>}
    </form>
  );
}

/** Settings, This book: the book's name, which a manager can change (it shows in the switcher and the Settings title). */
export default function ThisBook() {
  const book = useBook();
  return (
    <section className="spage" aria-labelledby="this-book-h">
      <h2 id="this-book-h">{S_THIS_BOOK}</h2>
      {book && <BookName book={book} />}
    </section>
  );
}
