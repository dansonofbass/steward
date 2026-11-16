import { BALANCE_NEEDED, LABEL, VALUE_NEEDED } from '../copy';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useBook } from '../../../book/BookContext';
import { Field } from '../../../ui/Field';
import { MoneyInput } from '../../../ui/MoneyInput';
import { defaultOwner, failure } from '../../settings/shared';
import { toHundredths } from '../../settings/money';
import { addAccount, patchAccount } from '../api';
import { invalidateProfile, useFieldMode } from '../field';

type Props = { type: 'property' | 'vehicle' | 'mortgage' | 'loan'; valueLabel: string; placeholder?: string; name?: string; /** The words for a missing or zero value. */ needed?: string;
  /** A loan's or mortgage's balance is what is owed: saved negative. */ owed?: boolean;
  /** Link the made account as this account's loan (a car's loan, a home's mortgage). */ linkTo?: number; /** The made account's name and its Undo tokens (the add, then the link). */ onMade: (name: string, undo: (string | null)[]) => void };

export function NewThing({ type, valueLabel, placeholder, name: fixedName, needed = VALUE_NEEDED, owed = false, linkTo, onMade }: Props) {
  const { register } = useFieldMode();
  const book = useBook();
  const qc = useQueryClient();
  const [name, setName] = useState(fixedName ?? '');
  const [value, setValue] = useState('');
  const [errors, setErrors] = useState<{ name?: string; value?: string }>({});
  const [failed, setFailed] = useState<string | null>(null);
  const latest = useRef({ name: fixedName ?? '', value: '' });
  const timer = useRef<number | null>(null);
  const made = useRef(false);
  const commit = useCallback(async (): Promise<boolean> => {
    if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null; }
    const { name: n, value: v } = latest.current;
    if (made.current || (n.trim() === (fixedName ?? '') && v.trim() === '')) return true;
    const cents = toHundredths(v);
    const e = { name: n.trim() ? undefined : LABEL, value: 'error' in cents || cents.value <= 0 ? (owed ? BALANCE_NEEDED : needed) : undefined };
    setErrors(e);
    if (e.name || e.value || 'error' in cents) return false;
    try {
      made.current = true;
      const a = await addAccount({ name: n.trim(), type, owner: defaultOwner(book?.owners), balance_cents: owed ? -cents.value : cents.value });
      const linked = linkTo !== undefined ? await patchAccount(linkTo, { loan_id: a.id }) : null;
      await invalidateProfile(qc);
      onMade(n.trim(), [a.undo, linked?.undo ?? null]);
      return true;
    } catch (err) {
      made.current = false;
      setFailed(failure(err));
      return false;
    }
  }, [book, fixedName, linkTo, needed, onMade, owed, qc, type]);
  useEffect(() => register(commit), [register, commit]);
  function change(n: string, v: string) {
    setName(n);
    setValue(v);
    latest.current = { name: n, value: v };
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void commit(), 600);
  }
  return (
    <div className="home-row">
      {fixedName === undefined && (
        <Field label={LABEL} error={errors.name}>
          <input autoFocus value={name} placeholder={placeholder} maxLength={120} autoComplete="off" onChange={(e) => change(e.target.value, value)} />
        </Field>
      )}
      <Field label={valueLabel} error={errors.value ?? failed ?? undefined}>
        <MoneyInput value={value} onValueChange={(v) => change(name, v)} />
      </Field>
    </div>
  );
}
