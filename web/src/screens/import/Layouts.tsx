import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useId, useRef, useState } from 'react';
import { api, json, patch } from '../../api/client';
import { useAccounts } from '../../api/hooks';
import { collapse } from '../../lib/collapse';
import { localYmd } from '../../lib/format';
import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import { Field } from '../../ui/Field';
import { Notice } from '../../ui/Notice';
import { UndoToast } from '../../ui/UndoToast';
import { failure } from '../settings/shared';
import type { Field as ColumnField, Mapping } from './api';
import * as C from './copy';
import { fieldAt, kindOf, monthDay, moveField, signCopy, validity } from './logic';

type LayoutRow = { id: number; label: string; header: string[]; mapping: Mapping; negate: boolean; date_format: string;
  last_used_at: string | null; uses: number; account_id: number | null; kind?: 'csv' | 'statement'; statement_kind?: string };
const keyOf = (r: LayoutRow) => `${r.kind ?? 'csv'}-${r.id}`;     // a row without a kind is a CSV layout
// A month-first format and its day-first twin, for Edit's two radios (dates with no twin read one way only).
const TWINS: Record<string, string> = { '%m/%d/%Y': '%d/%m/%Y', '%m/%d/%y': '%d/%m/%y', '%m-%d-%Y': '%d-%m-%Y' };
const twinOf = (f: string) => TWINS[f] ?? Object.keys(TWINS).find((k) => TWINS[k] === f) ?? null;
const useLayouts = () => useQuery({ queryKey: ['import-layouts'], queryFn: () => api<{ layouts: LayoutRow[] }>('/api/import/layouts') });

function Edit({ row, onDone }: { row: LayoutRow; onDone: () => void }) {
  const id = useId();
  const qc = useQueryClient();
  const accounts = useAccounts();
  const kind = kindOf(accounts.data?.accounts.find((a) => a.id === row.account_id)) ?? 'bank';
  const [label, setLabel] = useState(row.label);
  const [mapping, setMapping] = useState<Mapping>(row.mapping);
  const [negate, setNegate] = useState(row.negate);
  const [dateFormat, setDateFormat] = useState(row.date_format);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const twin = twinOf(row.date_format);
  const monthFirst = twin && row.date_format in TWINS ? row.date_format : twin;
  const copy = signCopy(kind, null);
  async function save() {
    setBusy(true);
    setError('');
    try {
      await api(`/api/import/layouts/${row.id}`, patch({ label: label.trim(), mapping, negate, date_format: dateFormat }));
      await qc.invalidateQueries({ queryKey: ['import-layouts'] });
      onDone();
    } catch (e) {
      setError(failure(e));
      setBusy(false);
    }
  }
  return (
    <div className="imp-confirm">
      <Field label={C.LAYOUT_NAME}><input value={label} maxLength={60} onChange={(e) => setLabel(e.target.value)} /></Field>
      <div className="table-wrap">
        <table className="table imp-confirm__table" style={{ minWidth: `${C.COL_REM * row.header.length}rem` }}>
          <caption className="sr-only">{C.COLUMNS_IN.replace('{file}', row.label)}</caption>
          <thead><tr>{row.header.map((h, i) => (
            <th key={i} scope="col">
              <select aria-label={C.COLUMN_N.replace('{n}', String(i + 1)).replace('{header}', h)} value={fieldAt(mapping, i)}
                onChange={(e) => setMapping(moveField(mapping, i, e.target.value as ColumnField | 'ignore'))}>
                {C.OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </th>
          ))}</tr></thead>
        </table>
      </div>
      {validity(mapping) !== 'ok' && <p className="imp-confirm__warn">{C.INVALID}</p>}
      {mapping.amount !== undefined && mapping.direction === undefined && (
        <fieldset className="imp-confirm__q">
          <legend className="sr-only">{C.NO_LEAN}</legend>
          {copy.options.map((l, i) => (
            <label key={l} className="imp-confirm__choice">
              <input type="radio" name={`${id}-sign`} checked={negate === (i === 0)} onChange={() => setNegate(i === 0)} />{l}
            </label>
          ))}
        </fieldset>
      )}
      {twin && monthFirst && (
        <fieldset className="imp-confirm__q">
          <legend className="sr-only">{C.DATES_READ.replace('{reading}', '')}</legend>
          {([[monthFirst, C.DATE_CHOICES.month], [TWINS[monthFirst], C.DATE_CHOICES.day]] as const).map(([f, l]) => (
            <label key={f} className="imp-confirm__choice">
              <input type="radio" name={`${id}-date`} checked={dateFormat === f} onChange={() => setDateFormat(f)} />{l}
            </label>
          ))}
        </fieldset>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      <div className="row-actions">
        <Button busy={busy} disabled={validity(mapping) !== 'ok' || !label.trim()} onClick={() => void save()}>{C.SAVE}</Button>
      </div>
    </div>
  );
}

/** P14: under Import, each remembered layout with Edit and Forget. Forget collapses the row and says so with Undo. */
export function Layouts() {
  const layouts = useLayouts();
  const qc = useQueryClient();
  const heading = useRef<HTMLHeadingElement>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [gone, setGone] = useState<Set<string>>(new Set());
  const [forgot, setForgot] = useState<{ label: string; undo: string; key: string } | null>(null);
  const [error, setError] = useState('');

  async function forget(row: LayoutRow, el: HTMLElement | null) {
    setError('');
    try {
      const path = row.kind === 'statement' ? 'statement-layouts' : 'layouts';
      const r = await api<{ undo: string }>(`/api/import/${path}/${row.id}`, { method: 'DELETE' });
      collapse(el, () => { setGone((s) => new Set(s).add(keyOf(row))); setForgot({ label: row.label, undo: r.undo, key: keyOf(row) }); heading.current?.focus(); });
    } catch (e) {
      setError(failure(e));
    }
  }

  async function undoForget() {
    if (!forgot) return;
    const f = forgot;
    setForgot(null);
    try {
      await api(`/api/undo/${f.undo}`, json({}));
      setGone((s) => { const n = new Set(s); n.delete(f.key); return n; });
      await qc.invalidateQueries({ queryKey: ['import-layouts'] });
    } catch (e) {
      setError(failure(e));
    }
  }

  const rows = (layouts.data?.layouts ?? []).filter((r) => !gone.has(keyOf(r)));
  return (
    <section className="step" aria-labelledby="layouts-h">
      <h3 id="layouts-h" className="subhead" tabIndex={-1} ref={heading}>{C.LAYOUTS}</h3>
      {error && <Notice tone="error">{error}</Notice>}
      {layouts.isSuccess && !layouts.isFetching && rows.length === 0 && <p className="muted">{C.NO_LAYOUTS}</p>}
      {rows.length > 0 && (
        <Card className="lines">
          <ul className="plain">
            {rows.map((r) => (
              <li key={keyOf(r)} className="imp-layout">
                <div className="line">
                  <span>{r.last_used_at ? (r.kind === 'statement' ? C.LAYOUT_STATEMENT_ROW : C.LAYOUT_ROW).replace('{label}', r.label).replace('{date}', monthDay(localYmd(r.last_used_at))) : r.label}</span>
                  <span className="imp-layout__actions">
                    {r.kind !== 'statement' && <Button variant="quiet" onClick={() => setEditing(editing === r.id ? null : r.id)}>{C.EDIT}</Button>}
                    <Button variant="quiet" onClick={(e) => void forget(r, (e.currentTarget as HTMLElement).closest('li'))}>{C.FORGET}</Button>
                  </span>
                </div>
                {r.kind !== 'statement' && editing === r.id && <Edit row={r} onDone={() => setEditing(null)} />}
              </li>
            ))}
          </ul>
        </Card>
      )}
      {forgot && <UndoToast key={`f-${forgot.key}`} text={C.FORGOT.replace('{label}', forgot.label)} onUndo={() => void undoForget()} onClose={() => setForgot(null)} />}
    </section>
  );
}
