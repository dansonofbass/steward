import { ChevronDown } from 'lucide-react';
import { useState } from 'react';
import { settle } from '../../api/reimburse';
import type { PayerBalance, SettleReply } from '../../api/types';
import { label } from '../../lib/categories';
import { SETTLE } from '../../lib/copy';
import { money } from '../../lib/format';
import { Button } from '../../ui/Button';
import { Field } from '../../ui/Field';
import { Notice } from '../../ui/Notice';
import { Sheet } from '../../ui/Sheet';
import { monthLong } from '../cashflow/months';
import * as C from './copy';
import { fill, SETTLE_CATEGORIES } from './model';

type Props = { payer: PayerBalance; month: string; onClose: () => void; onDone: (r: SettleReply) => void };

/** Settle (spec, Settling): the whole balance still owed becomes this month's spending in a category, defaulted to the
 *  one with the most dollars among the charges not yet paid back (rule 2). */
export function SettleSheet({ payer, month, onClose, onDone }: Props) {
  const [category, setCategory] = useState(payer.settle_category);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function go() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      onDone(await settle(payer.id, payer.owed_cents, category));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open onClose={onClose} title={SETTLE}>
      <div className="stack">
        <p>{fill(C.SETTLE_BODY, { amount: money(payer.owed_cents), payer: payer.name, month: monthLong(month) })}</p>
        <div className="select">
          <Field label={C.COUNTS_AS}>
            <select value={category} onChange={(e) => { setCategory(e.target.value); }}>
              {SETTLE_CATEGORIES.map((k) => <option key={k} value={k}>{label(k)}</option>)}
            </select>
          </Field>
          <ChevronDown size={20} aria-hidden="true" />
        </div>
        {error && <Notice tone="error">{error}</Notice>}
        <Button busy={busy} onClick={() => { void go(); }}>{SETTLE}</Button>
      </div>
    </Sheet>
  );
}
