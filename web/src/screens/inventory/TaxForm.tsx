import { useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, CircleCheck, Paperclip, Search, Upload } from 'lucide-react';
import { useRef, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useBook, useCanEdit } from '../../book/BookContext';
import { Link, Navigate } from '../../book/links';
import { Button } from '../../ui/Button';
import { Field } from '../../ui/Field';
import { MoneyInput } from '../../ui/MoneyInput';
import { Notice } from '../../ui/Notice';
import { toHundredths } from '../settings/money';
import { failure } from '../settings/shared';
import { importTaxForms, refreshInventory, saveTaxForm, uploadFile, type TaxResult } from './api';
import * as C from './copy';
import { fill, parentName, possessive } from './format';
import './inventory.css';
import { thisYear as householdYear } from '../../lib/today';

type Form = (typeof C.FORMS)[number];

export function TaxForm() {
  const book = useBook();
  const owners = book?.owners ?? [];
  const canEdit = useCanEdit();
  const names = possessive(parentName(book));
  const [sp] = useSearchParams();
  const thisYear = householdYear();
  const [form, setForm] = useState<Form>('1099-INT');
  const [year, setYear] = useState(String(thisYear - 1));
  const [recipient, setRecipient] = useState(owners.find((o) => o.key !== 'joint')?.key ?? owners[0]?.key ?? '');
  const [payer, setPayer] = useState('');
  const [last4, setLast4] = useState('');
  const [boxes, setBoxes] = useState<Record<string, string>>({});
  const [file, setFile] = useState<{ id: number; name: string } | null>(() => {
    const id = Number(sp.get('file'));
    return sp.get('file') && Number.isSafeInteger(id) && id > 0 ? { id, name: sp.get('name') ?? '' } : null;
  });
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<{ saved: number; list: TaxResult[] } | null>(null);
  const qc = useQueryClient();
  const formFile = useRef<HTMLInputElement>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const parsed: Record<string, number | string> = {};
    for (const [key, , name] of C.FORM_BOXES[form]) {
      const text = (boxes[key] ?? '').trim();
      if (!text) continue;
      if (key === 'box_7') { parsed[key] = text; continue; }
      const p = toHundredths(text);
      if ('error' in p) { setError(`${name}: ${p.error}`); return; }
      parsed[key] = p.value;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await saveTaxForm({ form, tax_year: Number(year), recipient, payer: payer.trim(), last4: last4.trim() || null,
        boxes: parsed, ...(file ? { file_id: file.id } : {}) });
      setResults({ saved: 1, list: [r] });
      await refreshInventory(qc);
    } catch (e2) {
      setError(failure(e2));
    } finally {
      setBusy(false);
    }
  }

  async function attach(f: File) {
    setError(null);
    setUploading(true);
    try {
      const r = await uploadFile(f, {}, () => undefined);
      setFile({ id: r.file.id, name: r.file.name });
    } catch (e) {
      setError(failure(e));
    } finally {
      setUploading(false);
    }
  }

  async function importCsv(f: File) {
    setBusy(true);
    setError(null);
    try {
      const r = await importTaxForms(f);
      setResults({ saved: r.saved, list: r.results });
      await refreshInventory(qc);
    } catch (e) {
      setError(failure(e));
    } finally {
      setBusy(false);
    }
  }

  function another() {
    setResults(null);
    setPayer('');
    setLast4('');
    setBoxes({});
    setFile(null);
  }

  if (!canEdit) return <Navigate to="/inventory" replace />;

  return (
    <div className="screen tax-form">
      <header className="page-head">
        <Link className="link back" to="/inventory/new"><ChevronLeft className="i" size={20} aria-hidden="true" />{C.ADD_AN_ITEM}</Link>
        <h1>{C.TAX_TITLE}</h1>
        <p className="muted">{fill(C.TAX_LEDE, { names })}</p>
      </header>
      {results ? (
        <div className="card stack">
          {results.saved > 1 && <p className="strong">{fill(C.CSV_SAVED, { n: results.saved })}</p>}
          {results.list.map((r, i) => (
            <div key={i} className="stack stack--tight">
              <p className="done-line"><CircleCheck size={20} aria-hidden="true" /><span className="ink strong">{r.headline}</span></p>
              <p className="small">{r.detail}</p>
            </div>
          ))}
          <div className="row-actions">
            <Link className="btn btn--primary" to="/inventory/suggestions"><span className="btn__content"><span>{fill(C.GO_TO_SUGGESTIONS, { names })}</span></span></Link>
            <Button variant="quiet" onClick={another}>{C.TYPE_ANOTHER}</Button>
          </div>
        </div>
      ) : (
        <form className="form" onSubmit={submit} noValidate>
          <fieldset className="stack stack--tight">
            <legend className="field__label">{C.FORM}</legend>
            <div className="inv-seg">
              {C.FORMS.map((f) => (
                <label key={f} className={form === f ? 'is-on' : ''}>
                  <input type="radio" name="form" checked={form === f} onChange={() => { setForm(f); setBoxes({}); }} />{f}
                </label>
              ))}
            </div>
            <p className="field__hint">{C.FORM_HINTS[form]}</p>
          </fieldset>
          <div className="boxes">
            <Field label={C.TAX_YEAR}>
              <select value={year} onChange={(e) => setYear(e.target.value)}>
                {Array.from({ length: 8 }, (_, i) => String(thisYear - i)).map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
            </Field>
            <Field label={C.RECIPIENT}>
              <select value={recipient} onChange={(e) => setRecipient(e.target.value)}>
                {owners.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
              </select>
            </Field>
            <Field label={C.PAYERS_NAME}><input value={payer} maxLength={120} onChange={(e) => setPayer(e.target.value)} /></Field>
            <Field label={C.LAST4_IF_SHOWN}><input value={last4} maxLength={4} inputMode="numeric" onChange={(e) => setLast4(e.target.value)} /></Field>
            {C.FORM_BOXES[form].map(([key, box, name]) => (
              <Field key={key} label={`${box} ${name}`}>
                {key === 'box_7'
                  ? <input value={boxes[key] ?? ''} maxLength={2} onChange={(e) => setBoxes((b) => ({ ...b, [key]: e.target.value }))} />
                  : <MoneyInput value={boxes[key] ?? ''} onValueChange={(v) => setBoxes((b) => ({ ...b, [key]: v }))} />}
              </Field>
            ))}
          </div>
          <div className="file-pick">
            <Paperclip size={20} aria-hidden="true" />
            {file ? <><span className="file-pick__name">{file.name}</span><span className="small muted">{C.ATTACHED_WORD}</span></>
              : <Button variant="quiet" disabled={uploading} onClick={() => formFile.current?.click()}>{C.ATTACH_THE_FORM}</Button>}
            <input ref={formFile} type="file" hidden aria-label={C.ATTACH_THE_FORM} accept=".pdf,.png,.jpg,.jpeg,.heic"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void attach(f); e.target.value = ''; }} />
          </div>
          {error && <Notice tone="error">{error}</Notice>}
          <div className="form-actions">
            <Button type="submit" icon={Search} busy={busy} disabled={uploading}>{fill(C.SAVE_AND_CHECK, { names })}</Button>
            <label className="link">
              <Upload size={20} aria-hidden="true" />{C.IMPORT_CSV}
              <input type="file" hidden accept=".csv,text/csv" aria-label={C.IMPORT_CSV}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) void importCsv(f); e.target.value = ''; }} />
            </label>
          </div>
          <p className="small muted">{C.CSV_HINT}</p>
        </form>
      )}
    </div>
  );
}

export default TaxForm;
