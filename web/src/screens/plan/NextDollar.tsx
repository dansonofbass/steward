import { useQueryClient } from '@tanstack/react-query';
import { ChevronRight, Circle, CircleCheck, CircleDashed, CircleHelp, CircleSlash, Clock, type LucideIcon } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { api, json, patch } from '../../api/client';
import { useCanEdit } from '../../book/BookContext';
import { Button } from '../../ui/Button';
import { Field } from '../../ui/Field';
import { Money } from '../../ui/Money';
import { MoneyInput } from '../../ui/MoneyInput';
import { formatMoneyInput, fromHundredths, toHundredths } from '../settings/money';
import { Notice } from '../../ui/Notice';
import { Sheet } from '../../ui/Sheet';
import { Skeleton } from '../../ui/Skeleton';
import { useNextDollar, type NextDollarData, type NextStep, type NextStepStatus } from './api';
import {
  CASH_MONTHS_LABEL, CASH_MONTHS_RANGE, CASH_NOW, DEBT_RATE_LABEL, HSA_NO, HSA_UNSURE, HSA_YES, IN_THIS_YEAR, MORE_A_YEAR,
  ND_ASK, ND_CANT_TELL, ND_CHANGE, ND_DONE, ND_LATER, ND_NO_ROOM, ND_SAVE, ND_SETTINGS_LINE, ND_SETTINGS_TITLE, ND_TO_DO,
  NEXT_DOLLAR_TITLE, OWED, PAYROLL_BLANK, PAYROLL_LABEL, PAYROLL_RANGE, RATE_FOR, RATE_RANGE, ROOM_LEFT, ROOM_LEFT_RULES, ROTH_LINK, ROTH_SHEET_TITLE, STILL_TO_ADD,
  SUGGESTS_ONLY,
} from './copy';

const STATUS: Record<NextStepStatus, { icon: LucideIcon; word: string; cls: string }> = {
  done: { icon: CircleCheck, word: ND_DONE, cls: 'done' },
  to_do: { icon: Circle, word: ND_TO_DO, cls: 'not' },
  later: { icon: Clock, word: ND_LATER, cls: 'cant' },
  ask: { icon: CircleHelp, word: ND_ASK, cls: 'not' },
  no_room: { icon: CircleSlash, word: ND_NO_ROOM, cls: 'cant' },
  cant_tell: { icon: CircleDashed, word: ND_CANT_TELL, cls: 'cant' },
};

const pct = (bp: number) => `${Number((bp / 100).toFixed(3))}%`;

/** "19.99", "19.99 %" or "7" as basis points; null for anything else ("22,9", "", "101"). */
export function parseRatePct(text: string): number | null {
  const t = text.trim().replace(/\s*%$/, '');
  if (!/^\d{1,3}(\.\d{1,3})?$/.test(t)) return null;
  const v = Number(t);
  return v <= 100 ? Math.round(v * 100) : null;
}

/** The figures under a step's title: what is in already and what is left, labelled for the step. */
export function figures(s: NextStep): { label: string; cents: number }[] {
  const out: { label: string; cents: number }[] = [];
  const add = (label: string, cents: number | null) => { if (cents !== null) out.push({ label, cents }); };
  if (s.status === 'ask') return out;
  switch (s.key) {
    case 'cash': add(CASH_NOW, s.in_cents); if (s.room_cents) add(STILL_TO_ADD, s.room_cents); break;
    case 'debt': if (s.room_cents) add(OWED, s.room_cents); break;
    case 'match': add(IN_THIS_YEAR, s.in_cents); if (s.room_cents) add(MORE_A_YEAR, s.room_cents); break;
    case 'invest': add(IN_THIS_YEAR, s.in_cents); if (s.choice === 'mortgage') add(OWED, s.room_cents); break;
    default:
      add(IN_THIS_YEAR, s.in_cents);
      // A step that waits for October shows no room figure (final review minor c).
      if (s.status !== 'no_room' && s.status !== 'later') add(s.rules_year ? ROOM_LEFT_RULES.replace('{year}', String(s.rules_year)) : ROOM_LEFT, s.room_cents);
  }
  return out;
}

function RateEntry({ account, onSaved }: { account: { account_id: number; name: string }; onSaved: () => Promise<unknown> }) {
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function save(e: FormEvent) {
    e.preventDefault();
    const bp = parseRatePct(text);
    if (bp === null) { setError(RATE_RANGE); return; }
    setBusy(true);
    setError(null);
    try {
      await api(`/api/accounts/${account.account_id}`, patch({ rate_bp: bp }));
      await onSaved();
    } catch (x) {
      setError((x as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="nd__rate" onSubmit={save} noValidate>
      <Field label={RATE_FOR.replace('{name}', account.name)} error={error}>
        <input type="text" inputMode="decimal" autoComplete="off" value={text} onChange={(e) => setText(e.target.value)} />
      </Field>
      <Button type="submit" variant="quiet" busy={busy}>{ND_SAVE}</Button>
    </form>
  );
}

/** What the paycheck put into the HSA or 401(k) this year, saved as a dated fact (final review ruling I3). */
function PayrollEntry({ payroll, onSaved }: { payroll: { key: string; cents: number | null }; onSaved: () => Promise<unknown> }) {
  const [text, setText] = useState(payroll.cents === null ? '' : formatMoneyInput(fromHundredths(payroll.cents)));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function save(e: FormEvent) {
    e.preventDefault();
    const c = toHundredths(text || '0');
    if ('error' in c || c.value < 0 || c.value > 10_000_000) { setError(PAYROLL_RANGE); return; }
    setBusy(true);
    setError(null);
    try {
      await api('/api/facts', json({ key: payroll.key, value: String(c.value) }));
      await onSaved();
    } catch (x) {
      setError((x as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="nd__rate" onSubmit={save} noValidate>
      <Field label={PAYROLL_LABEL} error={error}>
        <MoneyInput value={text} onValueChange={setText} autoComplete="off" />
      </Field>
      <Button type="submit" variant="quiet" busy={busy}>{ND_SAVE}</Button>
    </form>
  );
}

function SettingsForm({ settings, onDone, onSaved }: { settings: NextDollarData['settings']; onDone: () => void; onSaved: () => Promise<unknown> }) {
  const [months, setMonths] = useState(String(settings.cash_months));
  const [rate, setRate] = useState(String(Number((settings.debt_rate_bp / 100).toFixed(3))));
  const [error, setError] = useState<{ months?: string; rate?: string; save?: string }>({});
  const [busy, setBusy] = useState(false);
  async function save(e: FormEvent) {
    e.preventDefault();
    const m = /^\d{1,2}$/.test(months.trim()) ? Number(months.trim()) : NaN;
    const bp = parseRatePct(rate);
    const errs = { months: m >= 1 && m <= 24 ? undefined : CASH_MONTHS_RANGE, rate: bp === null ? RATE_RANGE : undefined };
    if (errs.months || errs.rate) { setError(errs); return; }
    setBusy(true);
    setError({});
    try {
      await api('/api/facts', json({ key: 'next_dollar.cash_months', value: String(m) }));
      await api('/api/facts', json({ key: 'next_dollar.debt_rate_bp', value: String(bp) }));
      await onSaved();
      onDone();
    } catch (x) {
      setError({ save: (x as Error).message });
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="stack" onSubmit={save} noValidate>
      <Field label={CASH_MONTHS_LABEL} error={error.months}>
        <input type="text" inputMode="numeric" value={months} onChange={(e) => setMonths(e.target.value)} />
      </Field>
      <Field label={DEBT_RATE_LABEL} error={error.rate}>
        <input type="text" inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} />
      </Field>
      {error.save && <Notice tone="error">{error.save}</Notice>}
      <Button type="submit" busy={busy}>{ND_SAVE}</Button>
    </form>
  );
}

/** Where the next dollar goes (cash-flow and tax spec section 6), on the Plan screen. Steward suggests; it never moves money. */
export function NextDollar() {
  const q = useNextDollar();
  const canEdit = useCanEdit();
  const qc = useQueryClient();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [backdoor, setBackdoor] = useState(false);
  const [hsaBusy, setHsaBusy] = useState(false);
  const [hsaError, setHsaError] = useState<string | null>(null);
  const refresh = () => Promise.all(['next-dollar', 'facts', 'accounts'].map((k) => qc.invalidateQueries({ queryKey: [k] })));

  async function answerHsa(value: 'yes' | 'no' | 'unsure') {
    setHsaBusy(true);
    setHsaError(null);
    try {
      await api('/api/facts', json({ key: 'health.hsa_plan', value }));
      await refresh();
    } catch (x) {
      setHsaError((x as Error).message);
    } finally {
      setHsaBusy(false);
    }
  }

  return (
    <section className="sec" aria-labelledby="nd-h">
      <h2 id="nd-h">{NEXT_DOLLAR_TITLE}</h2>
      {q.isError ? <Notice tone="error">{q.error.message}</Notice> : !q.data ? <Skeleton lines={6} /> : (
        <>
          <ol className="card nd">
            {q.data.steps.map((s, i) => {
              const st = STATUS[s.status];
              const Icon = st.icon;
              const figs = figures(s);
              return (
                <li key={s.key} className="nd__step" data-testid={`nd-${s.key}`}>
                  <span className="nd__title"><span className="nd__n">{i + 1}</span>{' '}{s.title}</span>
                  <span className={`status-pill status-pill--${st.cls}`}><Icon className="i" size={20} aria-hidden="true" />{st.word}</span>
                  {figs.length > 0 && (
                    <dl className="nd__figs">
                      {figs.map((f) => <div key={f.label}><dt>{f.label}</dt><dd><Money cents={f.cents} compact /></dd></div>)}
                    </dl>
                  )}
                  <p className="nd__why">{s.why}</p>
                  {s.choice === 'roth_ira' && s.status === 'no_room' && (
                    <button type="button" className="link" onClick={() => setBackdoor(true)}>{ROTH_LINK}<ChevronRight className="i" size={20} aria-hidden="true" /></button>
                  )}
                  {canEdit && s.key === 'hsa' && s.status === 'ask' && (
                    <div className="nd__answers">
                      <Button variant="quiet" disabled={hsaBusy} onClick={() => answerHsa('yes')}>{HSA_YES}</Button>
                      <Button variant="quiet" disabled={hsaBusy} onClick={() => answerHsa('no')}>{HSA_NO}</Button>
                      <Button variant="quiet" disabled={hsaBusy} onClick={() => answerHsa('unsure')}>{HSA_UNSURE}</Button>
                      {hsaError && <Notice tone="error">{hsaError}</Notice>}
                    </div>
                  )}
                  {s.payroll && s.payroll.cents === null && <p className="nd__why">{PAYROLL_BLANK}</p>}
                  {canEdit && s.payroll && <PayrollEntry key={`${s.payroll.key}-${s.payroll.cents}`} payroll={s.payroll} onSaved={refresh} />}
                  {canEdit && s.needs_rate.map((a) => <RateEntry key={a.account_id} account={a} onSaved={refresh} />)}
                </li>
              );
            })}
          </ol>
          <div className="nd__notes">
            <p className="nd__settings">
              <span>{ND_SETTINGS_LINE.replace('{months}', String(q.data.settings.cash_months)).replace('{rate}', pct(q.data.settings.debt_rate_bp))}</span>
              {canEdit && <button type="button" className="link" onClick={() => setSettingsOpen(true)}>{ND_CHANGE}</button>}
            </p>
            <p className="nd__foot">{SUGGESTS_ONLY}</p>
          </div>
          <Sheet open={backdoor} onClose={() => setBackdoor(false)} title={ROTH_SHEET_TITLE}><p>{q.data.backdoor_sheet}</p></Sheet>
          <Sheet open={settingsOpen} onClose={() => setSettingsOpen(false)} title={ND_SETTINGS_TITLE}>
            {settingsOpen && <SettingsForm settings={q.data.settings} onDone={() => setSettingsOpen(false)} onSaved={refresh} />}
          </Sheet>
        </>
      )}
    </section>
  );
}
