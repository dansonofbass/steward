import { useState, type FormEvent } from 'react';
import { api, patch } from '../../../api/client';
import { CANCEL, SAVE } from '../../../lib/copy';
import { dollars } from '../../../lib/format';
import { Button } from '../../../ui/Button';
import { Field } from '../../../ui/Field';
import { failure } from '../../settings/shared';
import { useRefreshInvestments, type InvestmentPage } from './api';
import { ADVISORY_LINE, ADVISORY_NONE, CHANGE, FEE_HINT, FEE_LABEL, FEE_RULE, SET } from './copy';
import { bpText } from './format';

const PERCENT = /^(?:\d(?:\.\d{1,2})?|\.\d{1,2})$/;

/** An adviser's yearly fee (investment views spec, Costs), set by hand on the account, for example Betterment's 0.25%.
 *  It counts in "All in" and in the Plan. Empty clears it. */
export function AdvisoryFee({ accountId, advisory, canEdit }: { accountId: number; advisory: InvestmentPage['advisory']; canEdit: boolean }) {
  const refresh = useRefreshInvestments();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(advisory ? bpText(advisory.fee_bp) : '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function save(e: FormEvent) {
    e.preventDefault();
    const t = text.trim();
    if (t !== '' && !PERCENT.test(t)) { setError(FEE_RULE); return; }
    setBusy(true);
    setError('');
    try {
      await api(`/api/accounts/${accountId}`, patch({ advisory_fee_bp: t === '' ? null : Math.round(Number(t) * 100) }));
      await refresh();
      setOpen(false);
    } catch (err) {
      setError(failure(err));
    }
    setBusy(false);
  }

  if (!advisory && !canEdit) return null;
  if (!open) {
    const line = advisory ? ADVISORY_LINE.replace('{pct}', bpText(advisory.fee_bp)).replace('{amount}', dollars(advisory.cost_cents)) : ADVISORY_NONE;
    return (
      <p className="inv-fee">
        <span>{line}</span>
        {canEdit && <> <button type="button" className="link" onClick={() => { setText(advisory ? bpText(advisory.fee_bp) : ''); setOpen(true); }}>{advisory ? CHANGE : SET}</button></>}
      </p>
    );
  }
  return (
    <form className="inv-feeform" onSubmit={save}>
      <Field label={FEE_LABEL} hint={FEE_HINT} error={error}>
        <input inputMode="decimal" value={text} autoFocus onChange={(e) => setText(e.target.value)} />
      </Field>
      <Button type="submit" busy={busy}>{SAVE}</Button>
      <Button variant="quiet" onClick={() => setOpen(false)}>{CANCEL}</Button>
    </form>
  );
}
