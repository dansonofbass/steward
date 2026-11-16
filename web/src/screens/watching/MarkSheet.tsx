import { Check, CircleCheck, Hourglass, Info } from 'lucide-react';
import { useState } from 'react';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { Sheet } from '../../ui/Sheet';
import { failure } from '../settings/shared';
import { changeNote, markChecking, markExpected, markHandled, type FlagPage } from './api';
import * as C from './copy';

export type Mode = 'expected' | 'handled' | 'checking' | 'note';
const TITLES: Record<Mode, string> = { expected: C.MARK_EXPECTED, handled: C.MARK_HANDLED, checking: C.MARK_CHECKING, note: C.CHANGE_NOTE };

/** README screens 3 and 4: a note is required for Handled and optional otherwise (decision 7); Expected offers the
 *  scope only on checks a known payee can quiet (decision 1). */
export function MarkSheet({ flag, mode, onClose, onDone }: { flag: FlagPage; mode: Mode | null; onClose: () => void; onDone: (page: FlagPage) => void }) {
  const scopes = flag.expected?.scopes ?? [];
  const [scope, setScope] = useState<string>(scopes.length ? 'about' : 'this');
  const [note, setNote] = useState(mode === 'note' ? flag.note ?? '' : '');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (mode === null) return null;
  async function save() {
    setBusy(true);
    setError(null);
    try {
      const out = mode === 'expected' ? await markExpected(flag.id, scope, note.trim())
        : mode === 'handled' ? await markHandled(flag.id, note.trim())
          : mode === 'checking' ? await markChecking(flag.id, note.trim()) : await changeNote(flag.id, note.trim());
      onDone(out);
    } catch (e) {
      setError(failure(e));
    } finally {
      setBusy(false);
    }
  }
  const icon = mode === 'expected' ? CircleCheck : mode === 'handled' ? Check : Hourglass;
  const label = mode === 'handled' ? C.WHAT_WAS_DONE : mode === 'note' ? C.NOTE : C.NOTE_OPTIONAL;
  return (
    <Sheet open onClose={onClose} title={TITLES[mode]}>
      <div className="stack">
        <p className="small muted">{flag.check_label}: {flag.summary}</p>
        {mode === 'expected' && scopes.length > 0 && (
          <fieldset className="stack stack--tight bare-fieldset">
            <legend className="field__label">{C.FLAG_AGAIN}</legend>
            <div className="card pick scope">
              {scopes.map((s) => (
                <label key={s.key} className={`radio-row${scope === s.key ? ' is-on' : ''}`}>
                  <input type="radio" name="scope" checked={scope === s.key} onChange={() => setScope(s.key)} />
                  <span className="stack stack--tight"><span className="strong">{s.title}</span><span className="small muted">{s.line}</span></span>
                </label>
              ))}
            </div>
          </fieldset>
        )}
        {mode === 'expected' && flag.expected?.fixed && <div className="key-callout"><Info size={20} aria-hidden="true" /><span>{flag.expected.fixed}</span></div>}
        {mode === 'expected' && flag.check === 'premium' && <p className="small muted">{C.PREMIUM_EXPECTED_NOTE}</p>}
        <div className="field">
          <label className="field__label" htmlFor="mark-note">{label}</label>
          <textarea id="mark-note" value={note} maxLength={300} placeholder={mode === 'expected' && !scopes.length ? C.EXPECTED_PLACEHOLDER : undefined}
            onChange={(e) => setNote(e.target.value)} />
          {mode === 'handled' && <span className="field__hint">{C.HANDLED_HINT}</span>}
        </div>
        {mode === 'expected' && scope !== 'this' && <p className="small muted">{C.SAVED_TO_KNOWN}</p>}
        {error && <Notice tone="error">{error}</Notice>}
        <div className="form-actions">
          <Button icon={icon} busy={busy} onClick={() => void save()}>{mode === 'note' ? C.SAVE_NOTE : TITLES[mode]}</Button>
          <Button variant="quiet" onClick={onClose}>{C.CANCEL}</Button>
        </div>
      </div>
    </Sheet>
  );
}
