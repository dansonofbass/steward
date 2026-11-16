import { useState, type FormEvent } from 'react';
import { api, put } from '../../../api/client';
import { CANCEL, SAVE } from '../../../lib/copy';
import { Button } from '../../../ui/Button';
import { Field } from '../../../ui/Field';
import { failure } from '../../settings/shared';
import { useRefreshInvestments, type HoldingRow } from './api';
import { ADD, COST_UNKNOWN, RATIO_LABEL } from './copy';

/** A fund the table doesn't know (investment views spec, Costs): "cost unknown · Add" lets a manager enter its expense
 *  ratio, saved as the household's override for that symbol in every account. A holding without a symbol can't be. */
export function CostAdd({ row }: { row: HoldingRow }) {
  const refresh = useRefreshInvestments();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await api('/api/expense-ratios', put({ symbol: row.symbol, ratio_pct: text.trim() }));
      await refresh();
      setOpen(false);
    } catch (err) {
      setError(failure(err));
    }
    setBusy(false);
  }

  if (!row.symbol) return <span className="muted">{COST_UNKNOWN}</span>;
  if (!open) {
    return <span className="muted"><span>{COST_UNKNOWN}</span> · <button type="button" className="link" onClick={() => setOpen(true)}>{ADD}</button></span>;
  }
  return (
    <form className="inv-costform" onSubmit={save}>
      <Field label={RATIO_LABEL.replace('{symbol}', row.symbol)} error={error}>
        <input inputMode="decimal" value={text} autoFocus onChange={(e) => setText(e.target.value)} />
      </Field>
      <Button type="submit" busy={busy}>{SAVE}</Button>
      <Button variant="quiet" onClick={() => setOpen(false)}>{CANCEL}</Button>
    </form>
  );
}
