import { Plus } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useChildren, type Child } from '../../../api/household';
import { answerSection, refreshProfile, undoToken } from '../../../api/profile';
import { useAccounts } from '../../../api/hooks';
import { useNavigate } from '../../../book/links';
import { Button } from '../../../ui/Button';
import { Field } from '../../../ui/Field';
import { Notice } from '../../../ui/Notice';
import { Skeleton } from '../../../ui/Skeleton';
import { UndoToast } from '../../../ui/UndoToast';
import { failure } from '../../settings/shared';
import { addChild, removeChild } from '../api';
import { ADDED, ADD_KID, BIRTH_YEAR, KID_NAME, KID_NAME_NEEDED, KID_YEAR_RANGE, NO_KIDS, REMOVE, REMOVE_NAMED, REMOVED } from '../copy';
import { invalidateProfile, useFieldMode } from '../field';
import { collapse } from '../motion';
import type { BodyProps } from '../sections';
import { useKidSave } from './kidSave';
import { SavedUndo } from './SavedUndo';

const range = () => { const y = new Date().getFullYear(); return { lo: y - 30, hi: y + 1 }; };
function check(name: string, year: string): { name?: string; year?: string } {
  const { lo, hi } = range();
  const out: { name?: string; year?: string } = {};
  if (name.trim() === '' || name.trim().length > 40) out.name = KID_NAME_NEEDED;
  const y = Number(year);
  if (!/^\d{4}$/.test(year.trim()) || y < lo || y > hi) out.year = KID_YEAR_RANGE.replace('{lo}', String(lo)).replace('{hi}', String(hi));
  return out;
}

/** A saved kid's row: Name and Birth year save 600 ms after typing, once both are valid. */
function KidRow({ kid, onRemove }: { kid: Child; onRemove: (kid: Child, row: HTMLElement | null) => void }) {
  const { save, error, undo, undoIt, busy } = useKidSave(kid.id);
  const [name, setName] = useState(kid.label);
  const [year, setYear] = useState(String(kid.birth_year));
  const [errors, setErrors] = useState<{ name?: string; year?: string }>({});
  const row = useRef<HTMLLIElement>(null);
  useEffect(() => {      // the server's values win after an Undo unless a change is still on its way
    if (busy()) return;
    setName(kid.label);
    setYear(String(kid.birth_year));
    setErrors({});
  }, [kid.label, kid.birth_year]); // eslint-disable-line react-hooks/exhaustive-deps
  function change(n: string, y: string) {
    setName(n);
    setYear(y);
    const e = check(n, y);
    setErrors(e);
    if (!e.name && !e.year) save({ label: n.trim(), birth_year: Number(y) }, 600);
  }
  return (
    <li ref={row} className="kid-row">
      <Field label={KID_NAME} error={errors.name}><input value={name} maxLength={40} autoComplete="off" onChange={(e) => change(e.target.value, year)} /></Field>
      <Field label={BIRTH_YEAR} error={errors.year ?? error ?? undefined}><input value={year} inputMode="numeric" onChange={(e) => change(name, e.target.value)} /></Field>
      <SavedUndo show={!!undo} onUndo={() => void undoIt()} />
      <Button variant="quiet" aria-label={REMOVE_NAMED.replace('{name}', kid.label)} onClick={() => onRemove(kid, row.current)}>{REMOVE}</Button>
    </li>
  );
}

/** The appended empty row (spec, Adding): focus in Name; it is made (POST) once both fields are valid. */
function NewKid({ onMade }: { onMade: (name: string, undo: string | null) => void }) {
  const { register } = useFieldMode();
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const [year, setYear] = useState('');
  const [errors, setErrors] = useState<{ name?: string; year?: string }>({});
  const [failed, setFailed] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  const latest = useRef({ name: '', year: '' });
  const made = useRef(false);
  const commit = useCallback(async (): Promise<boolean> => {
    if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null; }
    const { name: n, year: y } = latest.current;
    if (made.current || (n.trim() === '' && y.trim() === '')) return true;      // an untouched row holds nothing up
    const e = check(n, y);
    setErrors(e);
    if (e.name || e.year) return false;
    try {
      made.current = true;
      const r = await addChild({ label: n.trim(), birth_year: Number(y) });
      await invalidateProfile(qc);
      onMade(n.trim(), r.undo);
      return true;
    } catch (err) {
      made.current = false;
      setFailed(failure(err));
      return false;
    }
  }, [qc, onMade]);
  useEffect(() => register(commit), [register, commit]);
  function change(n: string, y: string) {
    setName(n);
    setYear(y);
    latest.current = { name: n, year: y };
    if (timer.current !== null) window.clearTimeout(timer.current);
    const e = check(n, y);
    if (!e.name && !e.year) timer.current = window.setTimeout(() => void commit(), 600);
  }
  return (
    <li className="kid-row">
      <Field label={KID_NAME} error={errors.name}><input autoFocus value={name} maxLength={40} autoComplete="off" onChange={(e) => change(e.target.value, year)} /></Field>
      <Field label={BIRTH_YEAR} error={errors.year ?? failed ?? undefined}><input value={year} inputMode="numeric" onChange={(e) => change(name, e.target.value)} /></Field>
    </li>
  );
}

export function KidsList(_: BodyProps) {
  const kids = useChildren();
  const accounts = useAccounts();
  const qc = useQueryClient();
  const nav = useNavigate();
  const [adding, setAdding] = useState(false);
  const [hidden, setHidden] = useState<number[]>([]);
  const [toast, setToast] = useState<{ text: string; token: string | null } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const loadError = kids.error ?? accounts.error;
  if (loadError) return <Notice tone="error">{loadError.message}</Notice>;
  if (!kids.data || !accounts.data) return <Skeleton lines={3} />;
  const list = kids.data.children.filter((k) => !hidden.includes(k.id));
  const has529 = accounts.data.accounts.some((a) => a.is_active && a.type === 'plan529');

  function remove(kid: Child, row: HTMLElement | null) {
    collapse(row, () => setHidden((h) => [...h, kid.id]));             // the row folds away, and a toast names it
    removeChild(kid.id).then(async (r) => {
      setToast({ text: REMOVED.replace('{name}', kid.label), token: r.undo });
      await invalidateProfile(qc);
    }).catch((e) => { setHidden((h) => h.filter((x) => x !== kid.id)); setFailed(failure(e)); });
  }
  async function undo() {
    const t = toast?.token;
    if (!t) { setToast(null); return; }
    try {
      await undoToken(t);
      setToast(null);
      setFailed(null);
      setHidden([]);
      await invalidateProfile(qc);
    } catch (e) {
      setFailed(failure(e));      // the toast and its Undo stay, so it can be tried again
    }
  }
  async function noKids() {
    try {
      await refreshProfile(qc, answerSection('kids', 'doesnt_apply'));
      nav('/profile');
    } catch (e) {
      setFailed(failure(e));
    }
  }
  return (
    <div className="stack">
      <ul className="plain kid-list">
        {list.map((k) => <KidRow key={k.id} kid={k} onRemove={remove} />)}
        {adding && <NewKid onMade={(name, token) => { setAdding(false); setToast({ text: ADDED.replace('{name}', name), token }); }} />}
      </ul>
      <div className="ob-form-actions">
        <Button variant="quiet" icon={Plus} onClick={() => setAdding(true)} disabled={adding}>{ADD_KID}</Button>
        {list.length === 0 && !adding && !has529 && <Button variant="quiet" onClick={() => void noKids()}>{NO_KIDS}</Button>}
      </div>
      {failed && <Notice tone="error">{failed}</Notice>}
      {toast && <UndoToast text={toast.text} onUndo={() => void undo()} onClose={() => setToast(null)} />}
    </div>
  );
}
