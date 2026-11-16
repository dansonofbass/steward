import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type FormEvent } from 'react';
import { SAVE } from '../../lib/copy';
import { dollars } from '../../lib/format';
import { Button } from '../../ui/Button';
import { Field } from '../../ui/Field';
import { MoneyInput } from '../../ui/MoneyInput';
import { Notice } from '../../ui/Notice';
import { Sheet } from '../../ui/Sheet';
import { fromHundredths, toHundredths } from '../settings/money';
import { failure } from '../settings/shared';
import { addScenario, careKey, editScenario, type CareOut, type CareScenario, type Level, type ScenarioFields } from './api';
import * as C from './copy';

type Draft = {
  level: Level; start: string; hours: string; days: string; room: 'shared' | 'private'; sell: boolean; sellYear: string;
  price: string; basis: string; selling: string; family: string; change: string;
};
const LEVELS: Level[] = ['at_home', 'in_home_help', 'assisted_living', 'memory_care', 'nursing_home'];
const text = (n: number | null | undefined) => (n == null || n === 0 ? '' : fromHundredths(n));

export function draftOf(s: CareScenario | null, thisYear: number): Draft {
  return {
    level: s?.level ?? 'assisted_living', start: s?.start_year && s.start_year > thisYear ? String(s.start_year) : 'now',
    hours: s?.hours_week ? String(s.hours_week) : '', days: String(s?.adult_day_days ?? 0), room: s?.room ?? 'shared',
    sell: s?.sell_home_year != null, sellYear: String(Math.max(s?.sell_home_year ?? thisYear, thisYear)),
    price: text(s?.home_price_cents), basis: s?.home_basis_cents != null ? fromHundredths(s.home_basis_cents) : '',
    selling: String((s?.selling_cost_bp ?? 600) / 100), family: text(s?.family_monthly_cents), change: text(s?.spending_change_monthly_cents),
  };
}

/** Typed text that isn't a whole number goes as typed, so the vault answers with its plain rule. */
export function bodyOf(d: Draft): ScenarioFields | { error: string } {
  const cents = (t: string): number | null => {
    if (!t.trim()) return null;
    const p = toHundredths(t);
    if ('error' in p) throw new Error(p.error);
    return p.value;
  };
  const whole = (t: string) => (/^\d+$/.test(t.trim()) ? Number(t.trim()) : t.trim()) as unknown as number;
  if (d.sell && !Number.isFinite(Number(d.selling))) return { error: C.SELLING_RULE };
  try {
    const inHome = d.level === 'in_home_help';
    return {
      level: d.level, start_year: d.level === 'at_home' || d.start === 'now' ? null : Number(d.start),
      hours_week: inHome ? whole(d.hours) : null, adult_day_days: inHome ? Number(d.days) : null,
      room: d.level === 'nursing_home' ? d.room : null, sell_home_year: d.sell ? Number(d.sellYear) : null,
      home_price_cents: d.sell ? cents(d.price) : null, home_basis_cents: d.sell ? cents(d.basis) : null,
      selling_cost_bp: d.sell ? Math.round(Number(d.selling) * 100) : 600,
      family_monthly_cents: cents(d.family) ?? 0, spending_change_monthly_cents: cents(d.change) ?? 0,
    };
  } catch (e) {
    return { error: (e as Error).message };
  }
}

export function ScenarioSheet({ open, scenario, data, onClose }: { open: boolean; scenario: CareScenario | null; data: CareOut; onClose: () => void }) {
  const qc = useQueryClient();
  const [d, setD] = useState<Draft>(() => draftOf(scenario, data.this_year));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (open) { setD(draftOf(scenario, data.this_year)); setError(null); }
  }, [open, scenario, data.this_year]);
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((p) => ({ ...p, [k]: v }));
  const years = Array.from({ length: 21 }, (_, i) => data.this_year + i);

  async function save(e: FormEvent) {
    e.preventDefault();
    const body = bodyOf(d);
    if ('error' in body) { setError(body.error); return; }
    setBusy(true);
    setError(null);
    try {
      qc.setQueryData(careKey, scenario ? await editScenario(scenario.id, body) : await addScenario(body));
      onClose();
    } catch (err) {
      setError(failure(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title={scenario ? C.CHANGE_TITLE : C.ADD_TITLE}>
      <form className="stack" onSubmit={save}>
        <fieldset className="care-level">
          <legend className="field__label">{C.KIND}</legend>
          {LEVELS.map((l) => (
            <label key={l}><input type="radio" name="care-level" value={l} checked={d.level === l} onChange={() => set('level', l)} />{C.LEVELS[l]}</label>
          ))}
        </fieldset>
        {d.level !== 'at_home' && (
          <Field label={C.STARTS}>
            <select value={d.start} onChange={(e) => set('start', e.target.value)}>
              <option value="now">{C.NOW}</option>
              {years.slice(1).map((y) => <option key={y} value={String(y)}>{y}</option>)}
            </select>
          </Field>
        )}
        {d.level === 'in_home_help' && (
          <div className="care-pair">
            <Field label={C.HOURS}><input inputMode="numeric" value={d.hours} onChange={(e) => set('hours', e.target.value)} /></Field>
            <Field label={C.DAYS}>
              <select value={d.days} onChange={(e) => set('days', e.target.value)}>
                {[0, 1, 2, 3, 4, 5].map((n) => <option key={n} value={String(n)}>{n}</option>)}
              </select>
            </Field>
          </div>
        )}
        {d.level === 'nursing_home' && (
          <fieldset className="care-level">
            <legend className="field__label">{C.ROOM}</legend>
            {(['shared', 'private'] as const).map((r) => (
              <label key={r}><input type="radio" name="care-room" value={r} checked={d.room === r} onChange={() => set('room', r)} />{C.ROOMS[r]}</label>
            ))}
          </fieldset>
        )}
        <label className="care-check"><input type="checkbox" checked={d.sell} onChange={(e) => set('sell', e.target.checked)} />{C.SELL}</label>
        {d.sell && (
          <div className="care-pair">
            <Field label={C.SELL_YEAR}>
              <select value={d.sellYear} onChange={(e) => set('sellYear', e.target.value)}>
                {years.map((y) => <option key={y} value={String(y)}>{y}</option>)}
              </select>
            </Field>
            <Field label={C.PRICE} hint={data.home_value_cents ? C.fill(C.PRICE_HINT, { value: dollars(data.home_value_cents) }) : undefined}>
              <MoneyInput value={d.price} onValueChange={(v) => set('price', v)} />
            </Field>
            <Field label={C.BASIS} hint={C.BASIS_HINT}><MoneyInput value={d.basis} onValueChange={(v) => set('basis', v)} /></Field>
            <Field label={C.SELLING}><input inputMode="decimal" value={d.selling} onChange={(e) => set('selling', e.target.value)} /></Field>
          </div>
        )}
        <Field label={C.FAMILY}><MoneyInput value={d.family} onValueChange={(v) => set('family', v)} post={C.A_MONTH} /></Field>
        <Field label={C.CHANGE_SPENDING} hint={C.CHANGE_HINT}><MoneyInput allowNegative value={d.change} onValueChange={(v) => set('change', v)} post={C.A_MONTH} /></Field>
        {error && <Notice tone="error">{error}</Notice>}
        <Button type="submit" busy={busy}>{SAVE}</Button>
      </form>
    </Sheet>
  );
}
