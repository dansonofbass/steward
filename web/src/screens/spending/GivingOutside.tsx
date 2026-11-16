import { useQueryClient } from '@tanstack/react-query';
import { Pencil } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { undoToken } from '../../api/profile';
import { saveGivingOutside } from '../../api/spending';
import { dollars } from '../../lib/format';
import { Button } from '../../ui/Button';
import { MoneyInput } from '../../ui/MoneyInput';
import { Notice } from '../../ui/Notice';
import { UndoToast } from '../../ui/UndoToast';
import { dollarsText, toHundredths } from '../settings/money';
import { failure } from '../settings/shared';
import * as C from './copy';
import { fill } from './format';

/** Giving outside these accounts (P13): a monthly fact on Giving's row only, never in money out, usual or the Plan.
 *  With none, a manager sees the prompt; with some, the sub-line says it and a pencil changes it. $0 clears it. One
 *  instance per row, in its sub-line, so the toast outlives the switch from prompt to phrase. */
export function GivingOutside({ cents, canEdit }: { cents: number; canEdit: boolean }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    const p = text.trim() === '' ? { value: 0 } : toHundredths(text);
    if ('error' in p) { setError(p.error); return; }
    setBusy(true);
    setError(null);
    try {
      const r = await saveGivingOutside(p.value);
      setOpen(false);
      setToken(r.undo);
      await qc.invalidateQueries({ queryKey: ['spending'] });
    } catch (err) {
      setError(failure(err));
    } finally {
      setBusy(false);
    }
  }
  async function undo() {
    const t = token;
    setToken(null);
    try { if (t) await undoToken(t); } catch (err) { setError(failure(err)); }
    await qc.invalidateQueries({ queryKey: ['spending'] });
  }
  const edit = () => { setText(cents > 0 ? dollarsText(cents) : ''); setOpen(true); };

  return (
    <>
      {cents > 0 && (
        <span className="sp-giving__phrase">
          {' · '}{fill(C.GIVING_LINE, { amount: dollars(cents) })}
          {canEdit && <button type="button" className="sp-giving__pencil" aria-label={C.GIVING_CHANGE} onClick={edit}><Pencil className="i" size={16} aria-hidden="true" /></button>}
        </span>
      )}
      {cents === 0 && canEdit && !open && (
        <span className="sp-giving__prompt">{C.GIVING_PROMPT} <button type="button" className="link" onClick={edit}>{C.ADD_IT}</button></span>
      )}
      {open && (
        <form className="sp-giving__form" onSubmit={(e) => void save(e)}>
          <label className="sp-giving__label">{C.GIVING_FIELD}
            <MoneyInput value={text} onValueChange={setText} autoFocus />
          </label>
          <Button type="submit" variant="quiet" busy={busy}>{C.SAVE}</Button>
        </form>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      {token && <UndoToast text={C.SAVED_TOAST} onUndo={() => void undo()} onClose={() => setToken(null)} />}
    </>
  );
}
