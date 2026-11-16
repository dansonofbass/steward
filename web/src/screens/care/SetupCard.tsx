import { useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { SAVE } from '../../lib/copy';
import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import { Field } from '../../ui/Field';
import { MoneyInput } from '../../ui/MoneyInput';
import { Notice } from '../../ui/Notice';
import { fromHundredths, toHundredths } from '../settings/money';
import { failure } from '../settings/shared';
import { STATES } from '../settings/states';
import { careKey, saveSetup, type CareOut } from './api';
import * as C from './copy';

/** Who Care is for and what it runs on (ruling 3). Text that isn't a whole year goes as typed, so the vault answers
 *  with its plain rule. */
const year = (t: string): number | string | null => (t.trim() === '' ? null : /^\d+$/.test(t.trim()) ? Number(t.trim()) : t.trim());

export function SetupCard({ data, onDone }: { data: CareOut; onDone: () => void }) {
  const qc = useQueryClient();
  const s = data.setup;
  const [person, setPerson] = useState(s?.person ?? data.people[0]?.key ?? '');
  const [born, setBorn] = useState(s ? String(s.birth_year) : '');
  const [spouse, setSpouse] = useState(s?.spouse_birth_year ? String(s.spouse_birth_year) : '');
  const [state, setState] = useState(s?.state ?? 'CA');
  const [growth, setGrowth] = useState(String((s?.care_inflation_bp ?? 400) / 100));
  const [spending, setSpending] = useState(s?.spending_monthly_cents != null ? fromHundredths(s.spending_monthly_cents) : '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    let spendingCents: number | null = null;
    if (spending.trim()) {
      const p = toHundredths(spending);
      if ('error' in p) { setError(p.error); return; }
      spendingCents = p.value;
    }
    if (!Number.isFinite(Number(growth)) || growth.trim() === '') { setError(C.GROWTH_RULE); return; }
    setBusy(true);
    setError(null);
    try {
      const out = await saveSetup({ person, birth_year: year(born), spouse_birth_year: year(spouse), state,
        care_inflation_bp: Math.round(Number(growth) * 100), spending_monthly_cents: spendingCents });
      qc.setQueryData(careKey, out);
      onDone();
    } catch (err) {
      setError(failure(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="stack form-card">
      <h2>{C.SET_UP_TITLE}</h2>
      <p className="muted">{C.SET_UP_WHY}</p>
      <form className="stack" onSubmit={save}>
        <Field label={C.WHO}>
          <select value={person} onChange={(e) => setPerson(e.target.value)}>
            {data.people.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select>
        </Field>
        <div className="care-pair">
          <Field label={C.BORN}><input inputMode="numeric" value={born} onChange={(e) => setBorn(e.target.value)} /></Field>
          <Field label={C.SPOUSE_BORN} hint={C.SPOUSE_HINT}><input inputMode="numeric" value={spouse} onChange={(e) => setSpouse(e.target.value)} /></Field>
        </div>
        <Field label={C.STATE}>
          <select value={state} onChange={(e) => setState(e.target.value)}>
            {STATES.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
          </select>
        </Field>
        <Field label={C.SPENDING} hint={C.SPENDING_HINT}><MoneyInput value={spending} onValueChange={setSpending} post={C.A_MONTH} /></Field>
        <Field label={C.GROWTH}><input inputMode="decimal" value={growth} onChange={(e) => setGrowth(e.target.value)} /></Field>
        {error && <Notice tone="error">{error}</Notice>}
        <Button type="submit" busy={busy} disabled={!person || !born.trim()}>{SAVE}</Button>
      </form>
    </Card>
  );
}
