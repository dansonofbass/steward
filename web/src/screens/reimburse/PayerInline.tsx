import { useQueryClient } from '@tanstack/react-query';
import { useId, useState, type KeyboardEvent } from 'react';
import { addPayer } from '../../api/reimburse';
import type { Payer } from '../../api/types';
import { SAVE } from '../../lib/copy';
import { composing } from '../../lib/ime';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import * as C from './copy';
import './reimburse.css';

type Props = { payers: Payer[]; value: number | null; onChoose: (id: number) => void };

/** Reimbursable spec, decision 6. With no payer yet: "Who pays you back?", asked once, then the new payer is chosen.
 *  With two or more: a small chooser. With exactly one, the caller doesn't render this. Loaded on demand (choice 20). */
export default function PayerInline({ payers, value, onChoose }: Props) {
  const qc = useQueryClient();
  const id = useId();
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (payers.length >= 2) {
    return (
      <label className="rb-inline">
        <span className="rb-inline__label">{C.WHO_PAYS}</span>
        <select value={value ?? ''} onChange={(e) => { onChoose(Number(e.target.value)); }}>
          {value === null && <option value="" disabled>{C.CHOOSE_ONE}</option>}
          {payers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </label>
    );
  }

  async function save() {
    if (busy || !name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const p = await addPayer(name.trim());
      onChoose(p.id);
      await qc.invalidateQueries({ queryKey: ['reimburse'] });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.');
    } finally {
      setBusy(false);
    }
  }
  // Inside the detail's form, Enter saves the payer, not the form.
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => { if (e.key === 'Enter') { e.preventDefault(); if (!composing(e)) void save(); } };

  return (
    <div className="rb-inline" role="group" aria-label={C.WHO_PAYS}>
      <label className="rb-inline__label" htmlFor={id}>{C.WHO_PAYS}</label>
      <input id={id} value={name} placeholder={C.PAYER_HINT} maxLength={60} autoComplete="organization"
        onChange={(e) => { setName(e.target.value); }} onKeyDown={onKey} />
      <Button variant="quiet" busy={busy} disabled={!name.trim()} onClick={() => { void save(); }}>{SAVE}</Button>
      {error && <Notice tone="error">{error}</Notice>}
    </div>
  );
}
