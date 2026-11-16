import { useQueryClient } from '@tanstack/react-query';
import { Archive, Check, ChevronLeft, ListPlus, Receipt } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import type { OwnerOption } from '../../api/types';
import { useBook, useCanEdit } from '../../book/BookContext';
import { Link, Navigate, useNavigate } from '../../book/links';
import { TRY_AGAIN } from '../../lib/copy';
import { radioKeys, radioTab } from '../../lib/radioKeys';
import { Button } from '../../ui/Button';
import { Field } from '../../ui/Field';
import { MoneyInput } from '../../ui/MoneyInput';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { dollarsText, toHundredths } from '../settings/money';
import { failure } from '../settings/shared';
import {
  addItem, closeItem, editItem, refreshInventory, useInventory, useItem, useSuggestions, type ItemDetail, type ItemKind, type ItemRow,
  type Suggestion,
} from './api';
import * as C from './copy';
import { fill, longLabel, parentName, possessive, todayIso } from './format';
import { KIND_ICONS } from './marks';
import './inventory.css';

type State = {
  kind: ItemKind; name: string; owner: string; institution: string; number: string; status: 'confirmed' | 'needs_checking';
  check_reason: string; data_source: string; login: string; notes: string; balance: string; balance_on: string; type: string;
  amount: string; frequency: string; ref: string; usual_day: string; renewal_on: string; match_text: string; original: string;
  signed_on: string; prepared_by: string; phone: string; email: string; looks_after: number[]; why: string; floor: string; floorWas: boolean;
  benefit: string; benefit_per: 'day' | 'month'; waiting: string; pool: string; years: string; rider: string;
};
const KINDS: ItemKind[] = ['account', 'income', 'insurance', 'document', 'contact'];
const str = (v: unknown) => (v === null || v === undefined ? '' : String(v));
const lastFour = (s: string) => s.replace(/[^0-9A-Za-z]/g, '').slice(-4).toUpperCase();

function blank(kind: ItemKind, owner: string): State {
  return {
    kind, name: '', owner, institution: '', number: '', status: 'confirmed', check_reason: '', data_source: 'manual', login: '',
    notes: '', balance: '', balance_on: todayIso(), type: '', amount: '', frequency: 'monthly', ref: '', usual_day: '',
    renewal_on: '', match_text: '', original: '', signed_on: '', prepared_by: '', phone: '', email: '', looks_after: [], why: '', floor: '', floorWas: false,
    benefit: '', benefit_per: 'day', waiting: '', pool: '', years: '', rider: '',
  };
}

/** Changing the kind keeps what every kind has (name, who, where, notes, login) and drops the rest, so a field typed for
 *  an insurance premium can't ride along into an income item. */
function switchKind(p: State, kind: ItemKind): State {
  return {
    ...blank(kind, p.owner), name: p.name, institution: p.institution, notes: p.notes, login: p.login, data_source: p.data_source,
    status: kind === 'contact' ? 'confirmed' : p.status, check_reason: p.check_reason,
  };
}

function fromValues(v: Record<string, unknown>, fallbackOwner: string): State {
  const kind = (KINDS.includes(v.kind as ItemKind) ? v.kind : 'account') as ItemKind;
  const d = (v.details ?? {}) as Record<string, unknown>;
  return {
    ...blank(kind, str(v.owner) || fallbackOwner), name: str(v.name), institution: str(v.institution), number: str(v.last4),
    status: v.status === 'needs_checking' ? 'needs_checking' : 'confirmed', check_reason: str(v.check_reason),
    data_source: str(v.data_source) || 'manual', login: str(v.login_kept_in), notes: str(v.notes),
    type: str(d.type ?? d.source ?? d.role), amount: d.amount_cents != null ? dollarsText(Number(d.amount_cents)) : '',
    frequency: str(d.frequency) || 'monthly', ref: str(kind === 'income' ? d.lands_in_id : d.paid_from_id),
    usual_day: str(d.usual_day), renewal_on: str(d.renewal_on), match_text: str(d.match_text), original: str(d.original_kept_in),
    signed_on: str(d.signed_on), prepared_by: str(d.prepared_by_id), phone: str(d.phone), email: str(d.email),
    looks_after: Array.isArray(d.looks_after_ids) ? (d.looks_after_ids as number[]) : [],
    floor: d.floor_cents != null ? dollarsText(Number(d.floor_cents)) : '', floorWas: d.floor_cents != null,
    benefit: d.benefit_cents != null ? dollarsText(Number(d.benefit_cents)) : '', benefit_per: d.benefit_per === 'month' ? 'month' : 'day',
    waiting: str(d.waiting_days), pool: d.pool_cents != null ? dollarsText(Number(d.pool_cents)) : '', years: str(d.benefit_years),
    rider: d.rider_bp != null ? String(Number(d.rider_bp) / 100) : '',
  };
}

function toBody(s: State, editing: boolean, isFeed: boolean): { body: Record<string, unknown> } | { error: string } {
  const cents = (t: string): number | null => {
    if (!t.trim()) return null;
    const p = toHundredths(t);
    if ('error' in p) throw new Error(p.error);
    return p.value;
  };
  const day = (t: string) => (t.trim() === '' ? null : Number.isInteger(Number(t)) ? Number(t) : t);
  const body: Record<string, unknown> = {
    name: s.name.trim(), owner: s.owner, institution: s.institution.trim() || null,
    login_kept_in: s.login.trim() || null, notes: s.notes.trim() || null,
  };
  if (!editing) body.kind = s.kind;
  if (s.kind !== 'contact') {
    body.status = s.status;
    if (s.status === 'needs_checking') body.check_reason = s.check_reason.trim() || null;
  }
  if ((s.kind === 'account' || s.kind === 'insurance') && s.number.trim()) body.number = s.number.trim();
  try {
    const d: Record<string, unknown> = {};
    if (s.kind === 'account') {
      d.type = s.type || null;
      if (C.FLOOR_TYPES.includes(s.type) && (s.floor.trim() || s.floorWas)) d.floor_cents = cents(s.floor);
      if (!isFeed) {
        body.data_source = s.data_source === 'statement' ? 'statement' : 'manual';
        const bal = cents(s.balance);
        if (bal !== null) { body.balance_cents = bal; body.balance_on = s.balance_on || null; }
      }
    } else if (s.kind === 'income' || s.kind === 'insurance') {
      d[s.kind === 'income' ? 'source' : 'type'] = s.type || null;
      d.amount_cents = cents(s.amount);
      d.frequency = s.frequency || null;
      d[s.kind === 'income' ? 'lands_in_id' : 'paid_from_id'] = s.ref ? Number(s.ref) : null;
      d.usual_day = day(s.usual_day);
      d.match_text = s.match_text.trim() || null;
      if (s.kind === 'insurance') d.renewal_on = s.renewal_on || null;
      if (s.kind === 'insurance' && s.type === 'long_term_care') {
        // Typed text that isn't a whole number goes as typed, so the vault answers with its plain rule.
        const whole = (t: string) => (t.trim() === '' ? null : /^\d+$/.test(t.trim()) ? Number(t.trim()) : t.trim());
        d.benefit_cents = cents(s.benefit);
        d.benefit_per = s.benefit.trim() ? s.benefit_per : null;
        d.waiting_days = whole(s.waiting);
        d.pool_cents = cents(s.pool);
        d.benefit_years = whole(s.years);
        d.rider_bp = s.rider.trim() === '' ? null : Number.isFinite(Number(s.rider)) ? Math.round(Number(s.rider) * 100) : s.rider.trim();
      }
      if (!editing && s.data_source !== 'manual') body.data_source = s.data_source;   // where a suggestion found it
    } else if (s.kind === 'document') {
      Object.assign(d, { type: s.type || null, original_kept_in: s.original.trim() || null, signed_on: s.signed_on || null,
        prepared_by_id: s.prepared_by ? Number(s.prepared_by) : null });
    } else {
      Object.assign(d, { role: s.type || null, phone: s.phone.trim() || null, email: s.email.trim() || null, looks_after_ids: s.looks_after });
    }
    body.details = d;
  } catch (e) {
    return { error: (e as Error).message };
  }
  if (editing && s.why.trim()) body.note = s.why.trim();
  return { body };
}

export function ItemForm() {
  const { id } = useParams();
  const editing = id !== undefined;
  const [sp] = useSearchParams();
  const sid = sp.get('suggestion');
  const item = useItem(Number(id), editing);
  const inv = useInventory();
  const sugs = useSuggestions(!editing && sid !== null);
  const book = useBook();
  const canEdit = useCanEdit();
  const owners = book?.owners ?? [];
  const fallback = owners.find((o) => o.key === 'joint')?.key ?? owners[0]?.key ?? '';
  if (!canEdit) return <Navigate to={editing ? `/inventory/${id}` : '/inventory'} replace />;   // ruling 8
  if (inv.isPending || (editing && item.isPending) || (sid !== null && sugs.isPending)) {
    return <div className="screen" aria-busy="true"><Skeleton lines={8} /></div>;
  }
  const error = inv.error ?? (editing ? item.error : null) ?? (sid !== null ? sugs.error : null);
  if (error) {
    const retry = () => { void inv.refetch(); if (editing) void item.refetch(); if (sid !== null) void sugs.refetch(); };
    return <div className="screen"><Notice tone="error"><p>{error.message}</p><Button variant="quiet" onClick={retry}>{TRY_AGAIN}</Button></Notice></div>;
  }
  const suggestion = sid !== null ? sugs.data?.suggestions.find((s) => String(s.id) === sid) ?? null : null;
  const kindParam = sp.get('kind') as ItemKind | null;
  const initial = editing && item.data
    ? { ...fromValues(item.data as unknown as Record<string, unknown>, fallback), number: '' }
    : suggestion ? fromValues(suggestion.prefill, fallback) : blank(kindParam && KINDS.includes(kindParam) ? kindParam : 'account', fallback);
  return <FormBody initial={initial} detail={editing ? item.data ?? null : null} suggestion={suggestion} suggestionGone={sid !== null && suggestion === null} items={inv.data?.items ?? []} owners={owners} names={possessive(parentName(book))} />;
}

function FormBody({ initial, detail, suggestion, suggestionGone, items, owners, names }: {
  initial: State; detail: ItemDetail | null; suggestion: Suggestion | null; suggestionGone: boolean; items: ItemRow[]; owners: OwnerOption[]; names: string;
}) {
  const editing = detail !== null;
  const [s, setS] = useState<State>(initial);
  const set = <K extends keyof State>(k: K, v: State[K]) => setS((p) => ({ ...p, [k]: v }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [closing, setClosing] = useState(false);
  const [closeBusy, setCloseBusy] = useState(false);
  const [closedOn, setClosedOn] = useState(todayIso());
  const [closeWhy, setCloseWhy] = useState('');
  const [closeError, setCloseError] = useState<string | null>(null);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const isFeed = detail?.data_source === 'feed';
  const open = items.filter((r) => r.status !== 'closed' && r.id !== detail?.id);
  const accounts = open.filter((r) => r.kind === 'account');
  const sources = s.kind === 'income' ? accounts : [...accounts, ...open.filter((r) => r.kind === 'income')];
  const contacts = open.filter((r) => r.kind === 'contact');
  const others = open.filter((r) => r.kind !== 'contact');
  const back = detail ? `/inventory/${detail.id}` : '/inventory';
  const instLabel = s.kind === 'account' ? (s.type === 'property' ? C.F.where : C.F.institution)
    : s.kind === 'insurance' ? C.INSURER : s.kind === 'income' ? C.PAYER : C.F.firm;
  const numberHint = editing && detail?.last4 ? fill(C.NUMBER_KEEP, { last4: detail.last4 })
    : s.number.trim() ? fill(C.NUMBER_HINT_SHOWN, { last4: lastFour(s.number) }) : C.NUMBER_HINT;

  async function submit(e: FormEvent) {
    e.preventDefault();
    const out = toBody(s, editing, isFeed);
    if ('error' in out) { setError(out.error); return; }
    setBusy(true);
    setError(null);
    try {
      const body = suggestion ? { ...out.body, suggestion_id: suggestion.id } : out.body;
      const saved = detail ? await editItem(detail.id, body) : await addItem(body);
      await refreshInventory(qc);
      navigate(`/inventory/${saved.id}`);
    } catch (e2) {
      setError(failure(e2));
    } finally {
      setBusy(false);
    }
  }

  async function close() {
    if (!detail) return;
    setCloseBusy(true);
    setCloseError(null);
    try {
      await closeItem(detail.id, { closed_on: closedOn, why: closeWhy });
      await refreshInventory(qc);
      navigate(`/inventory/${detail.id}`);
    } catch (e) {
      setCloseError(failure(e));
    } finally {
      setCloseBusy(false);
    }
  }

  return (
    <div className="screen item-form">
      <header className="page-head">
        <Link className="link back" to={back}><ChevronLeft className="i" size={20} aria-hidden="true" />{detail ? detail.name : C.BACK_TO_INVENTORY}</Link>
        <h1>{detail ? fill(C.EDIT_TITLE, { name: detail.name }) : C.ADD_TITLE}</h1>
      </header>
      {suggestionGone && <Notice tone="warn">{C.SUGGESTION_GONE}</Notice>}
      {suggestion && <Notice><ListPlus size={20} aria-hidden="true" /> {suggestion.filled_line}</Notice>}
      <form className="form" onSubmit={submit} noValidate>
        {!editing && (
          <section className="form-sec" aria-label={C.WHAT_IS_IT}>
            <h2 className="subhead">{C.WHAT_IS_IT}</h2>
            <div className="kinds" role="radiogroup" aria-label={C.KIND} onKeyDown={radioKeys}>
              {KINDS.map((k) => {
                const Icon = KIND_ICONS[k];
                const on = s.kind === k;
                return (
                  <button key={k} type="button" role="radio" aria-checked={on} tabIndex={radioTab(on)} className={`kind${on ? ' is-on' : ''}`}
                    onClick={() => setS((p) => switchKind(p, k))}>
                    <Icon size={20} aria-hidden="true" />{C.KIND_LABELS[k]}
                  </button>
                );
              })}
            </div>
            <Link className="link" to="/inventory/tax-form"><Receipt size={20} aria-hidden="true" />{C.FROM_TAX_FORM}</Link>
          </section>
        )}

        <section className="form-sec" aria-label={C.SECTION[s.kind]}>
          <h2 className="subhead">{C.SECTION[s.kind]}</h2>
          <div className="grid-2">
            <Field label={C.TYPE_LABEL[s.kind]}>
              <select value={s.type} onChange={(e) => set('type', e.target.value)}>
                <option value="">{C.CHOOSE}</option>
                {C.TYPE_OPTIONS[s.kind].map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </select>
            </Field>
            <Field label={C.NAME} hint={C.NAME_HINT}><input value={s.name} maxLength={120} onChange={(e) => set('name', e.target.value)} /></Field>
            {s.kind !== 'document' && <Field label={instLabel}><input value={s.institution} maxLength={120} onChange={(e) => set('institution', e.target.value)} /></Field>}
            {(s.kind === 'account' || s.kind === 'insurance') && (
              <Field label={s.kind === 'insurance' ? C.F.policyNumber : C.F.accountNumber} hint={numberHint}>
                <input value={s.number} maxLength={40} autoComplete="off" onChange={(e) => set('number', e.target.value)} />
              </Field>
            )}
            {s.kind === 'document' && (
              <>
                <Field label={C.F.originalKeptIn}><input value={s.original} maxLength={200} onChange={(e) => set('original', e.target.value)} /></Field>
                <Field label={C.DATE_SIGNED}><input type="date" value={s.signed_on} onChange={(e) => set('signed_on', e.target.value)} /></Field>
                <Field label={C.F.preparedBy}>
                  <select value={s.prepared_by} onChange={(e) => set('prepared_by', e.target.value)}>
                    <option value="">{C.NONE}</option>
                    {contacts.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                  </select>
                </Field>
              </>
            )}
            {s.kind === 'contact' && (
              <>
                <Field label={C.F.phone}><input type="tel" value={s.phone} maxLength={40} onChange={(e) => set('phone', e.target.value)} /></Field>
                <Field label={C.F.email}><input type="email" value={s.email} maxLength={200} onChange={(e) => set('email', e.target.value)} /></Field>
              </>
            )}
          </div>
          <fieldset className="stack stack--tight">
            <legend className="field__label">{C.WHOSE}</legend>
            <div className="inv-seg">
              {owners.map((o) => (
                <label key={o.key} className={s.owner === o.key ? 'is-on' : ''}>
                  <input type="radio" name="owner" checked={s.owner === o.key} onChange={() => set('owner', o.key)} />{o.label}
                </label>
              ))}
            </div>
          </fieldset>
        </section>

        {s.kind === 'account' && !isFeed && (
          <section className="form-sec" aria-label={C.DATA_FROM_Q}>
            <h2 className="subhead">{C.DATA_FROM_Q}</h2>
            <div className="inv-seg">
              {(['statement', 'manual'] as const).map((src) => (
                <label key={src} className={s.data_source === src ? 'is-on' : ''}>
                  <input type="radio" name="data_source" checked={s.data_source === src} onChange={() => set('data_source', src)} />{C.SOURCE_LABELS[src]}
                </label>
              ))}
            </div>
            <p className="field__hint">{C.DATA_FROM_HINT}</p>
            <div className="grid-2">
              <Field label={C.BALANCE}><MoneyInput allowNegative value={s.balance} onValueChange={(v) => set('balance', v)} /></Field>
              <Field label={C.BALANCE_ON}><input type="date" value={s.balance_on} onChange={(e) => set('balance_on', e.target.value)} /></Field>
            </div>
          </section>
        )}

        {s.kind === 'account' && C.FLOOR_TYPES.includes(s.type) && (
          <section className="form-sec">
            <Field label={C.FLOOR} hint={C.FLOOR_HINT}><MoneyInput value={s.floor} placeholder="" onValueChange={(v) => set('floor', v)} /></Field>
          </section>
        )}

        {(s.kind === 'income' || s.kind === 'insurance') && (
          <section className="form-sec" aria-label={C.MONEY_SECTION[s.kind]}>
            <h2 className="subhead">{C.MONEY_SECTION[s.kind]}</h2>
            <div className="grid-2">
              <Field label={s.kind === 'income' && (s.type === 'pension' || s.type === 'annuity') ? C.AMOUNT_BEFORE_TAX : C.AMOUNT}><MoneyInput value={s.amount} inputMode="decimal" onValueChange={(v) => set('amount', v)} /></Field>
              <Field label={C.HOW_OFTEN}>
                <select value={s.frequency} onChange={(e) => set('frequency', e.target.value)}>
                  {(s.kind === 'income' ? ['monthly', 'quarterly', 'yearly'] : ['monthly', 'quarterly', 'half_yearly', 'yearly'])
                    .map((f) => <option key={f} value={f}>{C.FREQUENCY_LABELS[f]}</option>)}
                </select>
              </Field>
              <Field label={s.kind === 'income' ? C.F.landsIn : C.F.paidFrom}>
                <select value={s.ref} onChange={(e) => set('ref', e.target.value)}>
                  <option value="">{C.NONE}</option>
                  {sources.map((r) => <option key={r.id} value={r.id}>{longLabel(r.name, r.institution, r.last4, r.kind)}</option>)}
                </select>
              </Field>
              <Field label={C.USUAL_DAY} hint={C.USUAL_DAY_HINT[s.kind]}><input inputMode="numeric" value={s.usual_day} onChange={(e) => set('usual_day', e.target.value)} /></Field>
              {s.kind === 'insurance' && <Field label={C.RENEWAL_DATE} hint={C.RENEWAL_HINT}><input type="date" value={s.renewal_on} onChange={(e) => set('renewal_on', e.target.value)} /></Field>}
              <Field label={C.MATCH_TEXT} hint={C.MATCH_HINT}><input value={s.match_text} maxLength={120} onChange={(e) => set('match_text', e.target.value)} /></Field>
            </div>
          </section>
        )}

        {s.kind === 'insurance' && s.type === 'long_term_care' && (
          <section className="form-sec" aria-label={C.LTC_SECTION}>
            <h2 className="subhead">{C.LTC_SECTION}</h2>
            <div className="grid-2">
              <Field label={C.LTC.benefit}><MoneyInput value={s.benefit} onValueChange={(v) => set('benefit', v)} /></Field>
              <Field label={C.LTC.per}>
                <select value={s.benefit_per} onChange={(e) => set('benefit_per', e.target.value === 'month' ? 'month' : 'day')}>
                  <option value="day">{C.LTC.perDay}</option>
                  <option value="month">{C.LTC.perMonth}</option>
                </select>
              </Field>
              <Field label={C.LTC.waiting} hint={C.LTC.waitingHint}><input inputMode="numeric" value={s.waiting} onChange={(e) => set('waiting', e.target.value)} /></Field>
              <Field label={C.LTC.pool} hint={C.LTC.poolHint}><MoneyInput value={s.pool} onValueChange={(v) => set('pool', v)} /></Field>
              <Field label={C.LTC.years}><input inputMode="numeric" value={s.years} onChange={(e) => set('years', e.target.value)} /></Field>
              <Field label={C.LTC.rider} hint={C.LTC.riderHint}><input inputMode="decimal" value={s.rider} onChange={(e) => set('rider', e.target.value)} /></Field>
            </div>
          </section>
        )}

        {s.kind !== 'contact' && (
          <section className="form-sec" aria-label={C.HOW_SURE}>
            <h2 className="subhead">{C.HOW_SURE}</h2>
            <div className="inv-radios">
              {(['confirmed', 'needs_checking'] as const).map((st) => (
                <label key={st} className={`radio-row${s.status === st ? ' is-on' : ''}`}>
                  <input type="radio" name="status" checked={s.status === st} onChange={() => set('status', st)} />
                  <span>{C.STATUS_LABELS[st]}<small>{st === 'confirmed' ? C.CONFIRMED_HINT[s.kind] : C.NEEDS_CHECKING_HINT}</small></span>
                </label>
              ))}
            </div>
            {s.status === 'needs_checking' && (
              <Field label={C.WHY_FIELD} hint={fill(C.WHY_FIELD_HINT, { names })}><input value={s.check_reason} maxLength={300} onChange={(e) => set('check_reason', e.target.value)} /></Field>
            )}
          </section>
        )}

        <section className="form-sec" aria-label={C.OTHER}>
          <h2 className="subhead">{C.OTHER}</h2>
          {s.kind === 'contact' && others.length > 0 && (
            <fieldset className="stack stack--tight">
              <legend className="field__label">{C.LOOKS_AFTER}</legend>
              {others.map((r) => (
                <label key={r.id} className="radio-row">
                  <input type="checkbox" checked={s.looks_after.includes(r.id)}
                    onChange={(e) => set('looks_after', e.target.checked ? [...s.looks_after, r.id] : s.looks_after.filter((x) => x !== r.id))} />
                  <span>{r.name}</span>
                </label>
              ))}
            </fieldset>
          )}
          <Field label={C.F.loginKeptIn} hint={C.LOGIN_HINT}><input value={s.login} maxLength={200} placeholder={C.LOGIN_PLACEHOLDER} onChange={(e) => set('login', e.target.value)} /></Field>
          <Field label={C.NOTES}><textarea value={s.notes} onChange={(e) => set('notes', e.target.value)} /></Field>
          {editing && <Field label={C.WHY_CHANGE} hint={C.WHY_CHANGE_HINT}><input value={s.why} maxLength={300} onChange={(e) => set('why', e.target.value)} /></Field>}
        </section>

        {error && <Notice tone="error">{error}</Notice>}
        <div className="form-actions">
          <Button type="submit" icon={Check} busy={busy}>{editing ? C.SAVE : C.ADD_ITEM}</Button>
          <Link className="btn btn--quiet" to={back}><span className="btn__content"><span>{C.CANCEL}</span></span></Link>
          {editing && <><span className="spacer" /><Button variant="danger" icon={Archive} onClick={() => setClosing(true)}>{C.CLOSE_ITEM}</Button></>}
        </div>
      </form>

      {closing && detail && (
        <div className="card stack" role="group" aria-label={fill(C.CLOSE_TITLE, { name: detail.name })}>
          <p className="strong">{fill(C.CLOSE_TITLE, { name: detail.name })}</p>
          <p className="small muted">{C.CLOSE_BODY}</p>
          <div className="grid-2">
            <Field label={C.CLOSED_ON}><input type="date" value={closedOn} onChange={(e) => setClosedOn(e.target.value)} /></Field>
            <Field label={C.CLOSE_WHY}><input value={closeWhy} maxLength={300} placeholder={C.CLOSE_WHY_PLACEHOLDER} onChange={(e) => setCloseWhy(e.target.value)} /></Field>
          </div>
          {closeError && <Notice tone="error">{closeError}</Notice>}
          <div className="row-actions">
            <Button variant="danger" busy={closeBusy} onClick={() => void close()}>{C.CLOSE_CONFIRM}</Button>
            <Button variant="quiet" onClick={() => setClosing(false)}>{C.KEEP_OPEN}</Button>
          </div>
        </div>
      )}
    </div>
  );
}

export default ItemForm;
