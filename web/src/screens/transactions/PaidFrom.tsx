import { useQueryClient } from '@tanstack/react-query';
import { ChevronRight, PiggyBank, Undo2 } from 'lucide-react';
import { useState } from 'react';
import { useSetAsides } from '../../api/hooks';
import { invalidateSetAsides, matchPayment, unmatchPayment } from '../../api/setasides';
import type { Txn } from '../../api/types';
import { useCanEdit, useIsHousehold } from '../../book/BookContext';
import { Link } from '../../book/links';
import { NOT_THIS_ONE, NO_SET_ASIDES_YET, PAID_FROM_A_SET_ASIDE, PAID_FROM_SETTING_ASIDE, PICK_SET_ASIDE } from '../../lib/copy';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';

type Props = { txn: Txn; onSaved: (t: Txn) => void };

/** Money out in a household book can be paid from a set-aside by hand; a matched payment says which and offers
 *  "Not this one" (not for a stopped set-aside, whose match is kept). The list loads only when the disclosure opens. */
export function PaidFrom({ txn, onSaved }: Props) {
  const qc = useQueryClient();
  const canEdit = useCanEdit();
  const household = useIsHousehold();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const list = useSetAsides(open && canEdit && household);
  const moneyOut = txn.amount_cents < 0 && !txn.is_transfer && txn.category !== 'transfer';
  if (!household || !moneyOut) return null;
  const matched = txn.set_aside ?? null;

  async function run(fn: () => Promise<unknown>, next: Txn) {
    setBusy(true); setError(null);
    try { await fn(); await invalidateSetAsides(qc); onSaved(next); setOpen(false); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  if (matched) {
    return (
      <div className="stack stack--tight sa-paid-from" data-testid="paid-from">
        <p className="small">
          <PiggyBank className="i" size={16} aria-hidden="true" /> {PAID_FROM_SETTING_ASIDE}<Link className="link" to={`/spending/setasides/${matched.id}`}>{matched.name}</Link>
          {canEdit && !matched.archived && <> · <button type="button" className="link" disabled={busy} onClick={() => void run(() => unmatchPayment(txn.id), { ...txn, set_aside: null })}><Undo2 className="i" size={16} aria-hidden="true" />{NOT_THIS_ONE}</button></>}
        </p>
        {error && <Notice tone="error">{error}</Notice>}
      </div>
    );
  }
  if (!canEdit) return null;
  const rows = list.data?.rows.filter((r) => !r.archived_at) ?? [];
  return (
    <div className="stack stack--tight sa-paid-from" data-testid="paid-from">
      <button type="button" className="link" aria-expanded={open} onClick={() => setOpen((o) => !o)}>{PAID_FROM_A_SET_ASIDE}<ChevronRight className="i" size={16} aria-hidden="true" /></button>
      {open && (
        list.isPending ? <Skeleton lines={2} /> : list.isError ? <Notice tone="error">{list.error.message}</Notice> : rows.length === 0 ? <p className="small muted">{NO_SET_ASIDES_YET}</p> : (
          <div className="stack stack--tight" role="group" aria-label={PICK_SET_ASIDE}>
            {rows.map((r) => (
              <button key={r.id} type="button" className="link" disabled={busy} onClick={() => void run(() => matchPayment(txn.id, r.id), { ...txn, set_aside: { id: r.id, name: r.name, how: 'hand', archived: false } })}>{r.name}</button>
            ))}
          </div>
        )
      )}
      {error && <Notice tone="error">{error}</Notice>}
    </div>
  );
}
