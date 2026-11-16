import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type FormEvent } from 'react';
import { SAVE } from '../../lib/copy';
import { Button } from '../../ui/Button';
import { Field } from '../../ui/Field';
import { MoneyInput } from '../../ui/MoneyInput';
import { Notice } from '../../ui/Notice';
import { Sheet } from '../../ui/Sheet';
import { fromHundredths, toHundredths } from '../settings/money';
import { failure } from '../settings/shared';
import { careKey, removeQuote, saveQuote, type CareCost } from './api';
import * as C from './copy';

const todayIso = () => {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};

/** A family's quote for one care cost, which replaces the typical figure (spec 4.2). Going back to the typical figure
 *  removes the quote with no Undo, so it asks first with the Care screen's inline Remove/Keep (T3). */
export function QuoteSheet({ cost, onClose, onRemoved }: { cost: CareCost | null; onClose: () => void; onRemoved?: (label: string) => void }) {
  const qc = useQueryClient();
  const [amount, setAmount] = useState('');
  const [on, setOn] = useState(todayIso());
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (cost) { setAmount(cost.quote ? fromHundredths(cost.quote.cents) : ''); setOn(cost.quote?.quoted_on ?? todayIso()); setError(null); setAsking(false); }
  }, [cost]);

  async function run(fn: () => Promise<unknown>, after?: () => void) {
    setBusy(true);
    setError(null);
    try {
      qc.setQueryData(careKey, await fn());
      after?.();
      onClose();
    } catch (err) {
      setError(failure(err));
    } finally {
      setBusy(false);
    }
  }
  function save(e: FormEvent) {
    e.preventDefault();
    if (!cost) return;
    const p = toHundredths(amount);
    if ('error' in p) { setError(p.error); return; }
    void run(() => saveQuote(cost.key, { cents: p.value, quoted_on: on }));
  }

  return (
    <Sheet open={cost !== null} onClose={onClose} title={cost ? C.fill(C.QUOTE_TITLE, { label: cost.label.toLowerCase() }) : ''}>
      {cost && (
        <form className="stack" onSubmit={save}>
          <Field label={C.QUOTE_AMOUNT}><MoneyInput value={amount} onValueChange={setAmount} post={C.PER[cost.per]} /></Field>
          <Field label={C.QUOTE_DATE}><input type="date" value={on} max={todayIso()} onChange={(e) => setOn(e.target.value)} /></Field>
          {error && <Notice tone="error">{error}</Notice>}
          <Button type="submit" busy={busy} disabled={!amount.trim()}>{SAVE}</Button>
          {cost.quote && (asking ? (
            <div className="stack stack--tight" role="group" aria-label={C.USE_TYPICAL_ASK}>
              <p className="small">{C.USE_TYPICAL_ASK}</p>
              <div className="care-actions">
                <Button variant="danger" busy={busy} aria-label={C.fill(C.REMOVE_QUOTE, { label: cost.label.toLowerCase() })}
                  onClick={() => void run(() => removeQuote(cost.key), () => onRemoved?.(cost.label))}>{C.REMOVE}</Button>
                <Button variant="quiet" onClick={() => setAsking(false)}>{C.KEEP}</Button>
              </div>
            </div>
          ) : <Button variant="quiet" onClick={() => setAsking(true)}>{C.USE_TYPICAL}</Button>)}
        </form>
      )}
    </Sheet>
  );
}
