// The accounts a person updates themselves: their list in Banks and accounts, and the sheets that add one and update
// a balance, which the Accounts tab's Add an account opens too.
import { useQueryClient } from '@tanstack/react-query';
import { Plus, RefreshCw } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { api, json, patch } from '../../api/client';
import { useAccounts } from '../../api/hooks';
import { useBook } from '../../book/BookContext';
import type { Account, AccountType, Owner } from '../../api/types';
import { localYmd, relativeDays } from '../../lib/format';
import {
  ADD_ACCOUNT, AS_OF, BALANCE, LAST_UPDATED, LOAN_AGAINST_IT, NAME, NO_BALANCE_YET, NO_MANUAL_ACCOUNTS, NONE, OWNER, SAVE, SAVED, TYPE, UPDATE_BALANCE, UPDATED_MANUALLY,
} from '../../lib/copy';
import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import { Field } from '../../ui/Field';
import { MoneyInput } from '../../ui/MoneyInput';
import { Money } from '../../ui/Money';
import { Notice } from '../../ui/Notice';
import { Sheet } from '../../ui/Sheet';
import { Skeleton } from '../../ui/Skeleton';
import { dollarsText, toHundredths } from '../settings/money';
import { defaultOwner, failure, ownerOptions, TYPE_OPTIONS, typeLabel } from '../settings/shared';

const todayYmd = () => localYmd(new Date().toISOString());

function useRefreshMoney() {
  const qc = useQueryClient();
  return () => Promise.all(['accounts', 'summary', 'history', 'transactions', 'spending', 'investment', 'contributions'].map((k) => qc.invalidateQueries({ queryKey: [k] })));
}

/** A vehicle's loan, for display (investment views spec): one of the book's loan accounts, or none. */
function LoanPicker({ value, onChange }: { value: number | null; onChange: (id: number | null) => void }) {
  const loans = (useAccounts().data?.accounts ?? []).filter((a) => a.type === 'loan');
  if (loans.length === 0) return null;
  return (
    <Field label={LOAN_AGAINST_IT}>
      <select value={value ?? ''} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
        <option value="">{NONE}</option>
        {loans.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
      </select>
    </Field>
  );
}

export function BalanceSheet({ account, onClose, onSaved }: { account: Account; onClose: () => void; onSaved: () => void }) {
  const refresh = useRefreshMoney();
  const [balance, setBalance] = useState(account.balance_cents === null ? '' : dollarsText(account.balance_cents));
  const [asOf, setAsOf] = useState(todayYmd);
  const [loanId, setLoanId] = useState<number | null>(account.loan_id ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function save(e: FormEvent) {
    e.preventDefault();
    const parsed = toHundredths(balance);
    if ('error' in parsed) { setError(parsed.error); return; }
    setBusy(true);
    setError('');
    try {
      await api(`/api/accounts/${account.id}/balance`, json({ balance_cents: parsed.value, as_of: asOf }));
      if (account.type === 'vehicle' && loanId !== (account.loan_id ?? null)) {
        await api(`/api/accounts/${account.id}`, patch({ loan_id: loanId }));
      }
      await refresh();
      onSaved();
    } catch (err) {
      setError(failure(err));
      setBusy(false);
    }
  }

  return (
    <Sheet open onClose={onClose} title={`Update ${account.name}`}>
      <form className="sheet-form" onSubmit={save}>
        <Field label={BALANCE} error={error}><MoneyInput allowNegative value={balance} onValueChange={setBalance} /></Field>
        <Field label={AS_OF}><input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></Field>
        {account.type === 'vehicle' && <LoanPicker value={loanId} onChange={setLoanId} />}
        <Button type="submit" busy={busy}>{SAVE}</Button>
      </form>
    </Sheet>
  );
}

/** The add form on its own, for a sheet that already shows (Add an account swaps it in, so focus stays put). */
export function AddAccountForm({ onSaved, autoFocus = false, initialName = '', initialType = 'checking' }: {
  onSaved: (id?: number) => void; autoFocus?: boolean; initialName?: string; initialType?: AccountType;
}) {
  const refresh = useRefreshMoney();
  const book = useBook();
  const [name, setName] = useState(initialName);
  const [type, setType] = useState<AccountType>(initialType);
  const [owner, setOwner] = useState<Owner>(() => defaultOwner(book?.owners));
  const [balance, setBalance] = useState('');
  const [asOf, setAsOf] = useState(todayYmd);
  const [loanId, setLoanId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<{ name?: string; balance?: string }>({});

  async function save(e: FormEvent) {
    e.preventDefault();
    const parsed = toHundredths(balance);
    const next: typeof errors = {};
    if (!name.trim()) next.name = 'Give the account a name.';
    if ('error' in parsed) next.balance = parsed.error;
    if (next.name || next.balance || 'error' in parsed) { setErrors(next); return; }
    setBusy(true);
    setErrors({});
    try {
      const made = await api<{ id: number }>('/api/accounts', json({ name: name.trim(), type, owner, balance_cents: parsed.value, as_of: asOf, ...(type === 'vehicle' && loanId ? { loan_id: loanId } : {}) }));
      await refresh();
      onSaved(made.id);
    } catch (err) {
      setErrors({ balance: failure(err) });
      setBusy(false);
    }
  }

  return (
    <form className="sheet-form" onSubmit={save}>
      <Field label={NAME} error={errors.name}><input value={name} maxLength={120} autoComplete="off" autoFocus={autoFocus} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label={TYPE}>
        <select value={type} onChange={(e) => setType(e.target.value as AccountType)}>
          {TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </Field>
      {type === 'vehicle' && <LoanPicker value={loanId} onChange={setLoanId} />}
      <Field label={OWNER}>
        <select value={owner} onChange={(e) => setOwner(e.target.value as Owner)}>
          {ownerOptions(book?.owners).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </Field>
      <Field label={BALANCE} hint={type === 'vehicle' ? "What it's worth today." : "For a loan or card, use a negative number."} error={errors.balance}>
        <MoneyInput allowNegative value={balance} onValueChange={setBalance} />
      </Field>
      <Field label={AS_OF}><input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></Field>
      <Button type="submit" busy={busy}>{SAVE}</Button>
    </form>
  );
}

export function AddAccountSheet({ onClose, onSaved, initialName, initialType }: {
  onClose: () => void; onSaved: (id?: number) => void; initialName?: string; initialType?: AccountType;
}) {
  return <Sheet open onClose={onClose} title={ADD_ACCOUNT}><AddAccountForm onSaved={onSaved} initialName={initialName} initialType={initialType} /></Sheet>;
}

/** Banks and accounts' "Updated manually" section: each account with its balance and Update balance, and Add account. */
export function ManualAccountsList() {
  const accounts = useAccounts();
  const [updating, setUpdating] = useState<Account | null>(null);
  const [adding, setAdding] = useState(false);
  const [saved, setSaved] = useState(false);
  const today = new Date();
  const manual = (accounts.data?.accounts ?? []).filter((a) => a.source === 'manual');
  return (
    <>
      <section className="spage" aria-labelledby="manual-h">
        <div className="section-head">
          <h3 className="subhead" id="manual-h">{UPDATED_MANUALLY}</h3>
          <Button variant="quiet" icon={Plus} onClick={() => { setSaved(false); setAdding(true); }}>{ADD_ACCOUNT}</Button>
        </div>
        {saved && <Notice>{SAVED}</Notice>}
        {accounts.isPending && <Card><Skeleton lines={3} /></Card>}
        {accounts.isError && <Notice tone="error">{accounts.error.message}</Notice>}
        {accounts.isSuccess && (
          <Card className="lines">
            <ul className="plain">
              {manual.map((a) => (
                <li className="line" key={a.id}>
                  <div className="line__main">
                    <span id={`acct-${a.id}`}>{a.name}</span>
                    <span className="small muted">{typeLabel(a.type)} · {a.as_of ? LAST_UPDATED.replace('{when}', relativeDays(a.as_of, today)) : NO_BALANCE_YET}</span>
                  </div>
                  {a.balance_cents !== null && <Money cents={a.balance_cents} />}
                  <Button variant="quiet" icon={RefreshCw} aria-describedby={`acct-${a.id}`} onClick={() => { setSaved(false); setUpdating(a); }}>{UPDATE_BALANCE}</Button>
                </li>
              ))}
              {manual.length === 0 && <li className="line line--empty">{NO_MANUAL_ACCOUNTS}</li>}
            </ul>
          </Card>
        )}
      </section>
      {updating && <BalanceSheet account={updating} onClose={() => setUpdating(null)} onSaved={() => { setUpdating(null); setSaved(true); }} />}
      {adding && <AddAccountSheet onClose={() => setAdding(false)} onSaved={() => { setAdding(false); setSaved(true); }} />}
    </>
  );
}
