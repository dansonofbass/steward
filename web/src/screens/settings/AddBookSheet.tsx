import { useQueryClient } from '@tanstack/react-query';
import { Plus, X } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, json } from '../../api/client';
import type { BookSummary } from '../../api/types';
import { bookHref } from '../../book/BookContext';
import { ADD_A_BOOK, ADD_A_NAME, ADD_BOOK, BOOK_NAME_HINT, NAME, OWNER_NAMES, OWNER_NAMES_HINT, OWNER_NAME_PLACEHOLDER } from '../../lib/copy';
import { Button } from '../../ui/Button';
import { Field } from '../../ui/Field';
import { Notice } from '../../ui/Notice';
import { Sheet } from '../../ui/Sheet';
import { failure } from './shared';
import './members.css';

/** Add a book: Settings' Books, Get Steward ready and the first run's extras open it. A lazy chunk: Books loads it
 *  when the person can add a book, not with the first download (guided setup spec 11).
 *  With `onAdded` the page stays where it is (the first run's extras); without it, the new book's members open. */
export function AddBookSheet({ onClose, onAdded }: { onClose: () => void; onAdded?: (b: BookSummary) => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [owners, setOwners] = useState<string[]>(['', 'Joint']);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const owner_names = owners.map((o) => o.trim()).filter(Boolean);
      const r = await api<{ book: BookSummary }>('/api/books', json({ name: name.trim(), kind: 'parent', owner_names }));
      await qc.invalidateQueries({ queryKey: ['me'] });
      if (onAdded) onAdded(r.book);
      else navigate(bookHref(r.book.slug, '/settings/members'), { state: { added: r.book.name } });
    } catch (err) {
      setError(failure(err));
      setBusy(false);
    }
  }

  return (
    <Sheet open onClose={onClose} title={ADD_A_BOOK}>
      <form className="sheet-form" onSubmit={save}>
        <Field label={NAME} hint={BOOK_NAME_HINT}>
          <input value={name} maxLength={60} autoComplete="off" onChange={(e) => setName(e.target.value)} />
        </Field>
        <fieldset className="owners">
          <legend className="field__label">{OWNER_NAMES}</legend>
          {owners.map((o, i) => (
            <div className="owners__row" key={i}>
              <input aria-label={`${OWNER_NAMES} ${i + 1}`} value={o} maxLength={40}
                placeholder={i === 0 ? OWNER_NAME_PLACEHOLDER : undefined}
                onChange={(e) => setOwners(owners.map((x, j) => (j === i ? e.target.value : x)))} />
              {owners.length > 1 && (
                <button type="button" className="icon-btn" aria-label={`Remove ${o.trim() || `${OWNER_NAMES} ${i + 1}`}`}
                  onClick={() => setOwners(owners.filter((_, j) => j !== i))}>
                  <X size={20} aria-hidden="true" />
                </button>
              )}
            </div>
          ))}
          <p className="field__hint">{OWNER_NAMES_HINT}</p>
          {owners.length < 8 && <div><Button variant="quiet" icon={Plus} onClick={() => setOwners([...owners, ''])}>{ADD_A_NAME}</Button></div>}
        </fieldset>
        {error && <Notice tone="error">{error}</Notice>}
        <Button type="submit" busy={busy}>{ADD_BOOK}</Button>
      </form>
    </Sheet>
  );
}

export default AddBookSheet;
