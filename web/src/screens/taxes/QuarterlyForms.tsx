import { useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { currentBook } from '../../api/book';
import { useCanEdit } from '../../book/BookContext';
import { dollars } from '../../lib/format';
import { setQueryDataIfStillIn } from '../../queryClient';
import { Button } from '../../ui/Button';
import { Field, FormError } from '../../ui/Field';
import { MoneyInput } from '../../ui/MoneyInput';
import { dollarsText, toHundredths } from '../settings/money';
import { failure } from '../settings/shared';
import { QUARTERLY_KEY, markPayment, saveReturn, saveWithholding, setEmail, type PaymentOut, type QuarterlyOut, type Unavailable } from './api';
import * as C from './copy';

type Put = (next: QuarterlyOut) => void;

function useApply(): Put {
  const qc = useQueryClient();
  const book = currentBook();
  return (next) => {
    setQueryDataIfStillIn<QuarterlyOut | Unavailable>(qc, book, QUARTERLY_KEY, () => next);
    void qc.invalidateQueries({ queryKey: ['taxes', 'notice'] });
  };
}

const text = (cents: number | null | undefined) => (cents == null ? '' : dollarsText(cents));

/** Blank is null; otherwise whole cents, or the parse error. */
function cents(value: string): { value: number | null } | { error: string } {
  if (value.trim() === '') return { value: null };
  return toHundredths(value);
}

export function Payments({ data }: { data: QuarterlyOut }) {
  const canEdit = useCanEdit();
  const apply = useApply();
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function toggle(p: PaymentOut) {
    setBusy(p.id);
    setError(null);
    try {
      apply(await markPayment(p.id, !p.counts));
    } catch (e) {
      setError(failure(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="stack stack--tight">
      <h3>{C.PAYMENTS}</h3>
      {data.payments.length === 0 ? <p className="small muted">{C.NO_PAYMENTS.replace('{year}', String(data.year))}</p> : (
        <ul className="tax-list">
          {data.payments.map((p) => (
            <li key={p.id}>
              <span>{p.posted_label} · {p.label}</span>
              <span className="tax-num">{dollars(p.amount_cents)}</span>
              <span className="small muted">{p.counts ? p.description : `${C.NOT_COUNTED}: ${p.description}`}</span>
              {canEdit && (
                <Button variant="quiet" busy={busy === p.id} onClick={() => void toggle(p)}>
                  {p.counts ? C.NOT_ESTIMATE : C.COUNT_IT}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {error && <FormError>{error}</FormError>}
    </section>
  );
}

export function ReturnForm({ data }: { data: QuarterlyOut }) {
  const canEdit = useCanEdit();
  const apply = useApply();
  const p = data.prior;
  const ca = data.state === 'CA' && data.agencies.some((a) => a.agency === 'state');
  const [editing, setEditing] = useState(p === null);
  const [f, setF] = useState(() => ({ ft: text(p?.federal_tax_cents), fa: text(p?.federal_agi_cents),
    st: text(p?.state_tax_cents), sa: text(p?.state_agi_cents) }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const year = String(data.prior_year);

  async function save(e: FormEvent) {
    e.preventDefault();
    const parsed = [cents(f.ft), cents(f.fa), cents(f.st), cents(f.sa)];
    const bad = parsed.find((x) => 'error' in x);
    if (bad && 'error' in bad) { setError(bad.error); return; }
    const [ft, fa, st, sa] = parsed.map((x) => ('value' in x ? x.value : null));
    setBusy(true);
    setError(null);
    try {
      apply(await saveReturn(data.prior_year, { federal_tax_cents: ft, federal_agi_cents: fa, state_tax_cents: st, state_agi_cents: sa }));
      setEditing(false);
    } catch (err) {
      setError(failure(err));
    } finally {
      setBusy(false);
    }
  }

  if (!canEdit && p === null) return null;
  return (
    <section className="stack stack--tight">
      <h3>{C.RETURN.replace('{year}', year)}</h3>
      {!editing && p && (
        <>
          {p.federal_tax_cents != null && p.federal_agi_cents != null && (
            <p className="small">{C.RETURN_SUMMARY.replace('{tax}', dollars(p.federal_tax_cents)).replace('{agi}', dollars(p.federal_agi_cents))}</p>
          )}
          {p.state_tax_cents != null && p.state_agi_cents != null && (
            <p className="small">{C.RETURN_SUMMARY_CA.replace('{tax}', dollars(p.state_tax_cents)).replace('{agi}', dollars(p.state_agi_cents))}</p>
          )}
          {canEdit && <Button variant="quiet" onClick={() => setEditing(true)}>{C.CHANGE}</Button>}
        </>
      )}
      {editing && canEdit && (
        <form className="tax-entry" onSubmit={save}>
          <Field label={C.FED_TAX}><MoneyInput value={f.ft} onValueChange={(v) => setF({ ...f, ft: v })} /></Field>
          <Field label={C.FED_AGI}><MoneyInput value={f.fa} onValueChange={(v) => setF({ ...f, fa: v })} /></Field>
          {ca && <Field label={C.CA_TAX}><MoneyInput value={f.st} onValueChange={(v) => setF({ ...f, st: v })} /></Field>}
          {ca && <Field label={C.CA_AGI}><MoneyInput value={f.sa} onValueChange={(v) => setF({ ...f, sa: v })} /></Field>}
          <div className="tax-entry__actions">
            <Button type="submit" busy={busy}>{C.SAVE_RETURN.replace('{year}', year)}</Button>
            {p && <Button variant="quiet" onClick={() => setEditing(false)}>{C.CANCEL}</Button>}
          </div>
          {error && <FormError>{error}</FormError>}
        </form>
      )}
    </section>
  );
}

export function WithholdingForm({ data }: { data: QuarterlyOut }) {
  const canEdit = useCanEdit();
  const apply = useApply();
  const w = data.withholding;
  const ca = data.state === 'CA';
  const yr = String(data.year);                    // the card's year: in early January, last year's (final review I1)
  const [editing, setEditing] = useState(w === null);
  const [f, setF] = useState(() => ({ fed: text(w?.federal_ytd_cents), st: text(w?.state_ytd_cents), asOf: w?.as_of ?? '' }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    const fed = toHundredths(f.fed || '0');
    const st = toHundredths(f.st || '0');
    if ('error' in fed) { setError(fed.error); return; }
    if ('error' in st) { setError(st.error); return; }
    setBusy(true);
    setError(null);
    try {
      apply(await saveWithholding(data.year, { federal_ytd_cents: fed.value, state_ytd_cents: st.value, as_of: f.asOf }));
      setEditing(false);
    } catch (err) {
      setError(failure(err));
    } finally {
      setBusy(false);
    }
  }

  if (!canEdit && w === null) return null;
  return (
    <section className="stack stack--tight">
      <h3>{C.WITHHOLDING}</h3>
      {!editing && w && (
        <>
          <p className="small">{C.WITHHOLDING_SUMMARY.replace('{date}', w.as_of_label).replace('{federal}', dollars(w.federal_ytd_cents))
            .replace('{state}', dollars(w.state_ytd_cents))}</p>
          {canEdit && <Button variant="quiet" onClick={() => setEditing(true)}>{C.CHANGE}</Button>}
        </>
      )}
      {editing && canEdit && (
        <form className="tax-entry" onSubmit={save}>
          <Field label={C.FED_WITHHELD.replace('{year}', yr)}><MoneyInput value={f.fed} onValueChange={(v) => setF({ ...f, fed: v })} /></Field>
          {ca && <Field label={C.CA_WITHHELD.replace('{year}', yr)}><MoneyInput value={f.st} onValueChange={(v) => setF({ ...f, st: v })} /></Field>}
          <Field label={C.PAY_DATE.replace('{year}', yr)}>
            <input type="date" value={f.asOf} min={`${yr}-01-01`} max={`${yr}-12-31`}
              onChange={(e) => setF({ ...f, asOf: e.target.value })} required />
          </Field>
          <div className="tax-entry__actions">
            <Button type="submit" busy={busy}>{C.SAVE_WITHHOLDING}</Button>
            {w && <Button variant="quiet" onClick={() => setEditing(false)}>{C.CANCEL}</Button>}
          </div>
          {error && <FormError>{error}</FormError>}
        </form>
      )}
    </section>
  );
}

export function EmailSwitch({ on }: { on: boolean }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function change(next: boolean) {
    setBusy(true);
    setError(null);
    const book = currentBook();
    try {
      const r = await setEmail(next);
      setQueryDataIfStillIn<QuarterlyOut | Unavailable>(qc, book, QUARTERLY_KEY, (old) => (old && old.available ? { ...old, email_on: r.on } : old));
    } catch (e) {
      setError(failure(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <label className="tax-check">
        <input type="checkbox" checked={on} disabled={busy} onChange={(e) => void change(e.target.checked)} />
        {C.EMAIL_ME}
      </label>
      {error && <FormError>{error}</FormError>}
    </div>
  );
}
