import { useState, type FormEvent } from 'react';
import { api } from '../../../api/client';
import { AS_OF, PREVIEW, SAVE } from '../../../lib/copy';
import { dollars } from '../../../lib/format';
import { Button } from '../../../ui/Button';
import { Field } from '../../../ui/Field';
import { Notice } from '../../../ui/Notice';
import { Sheet } from '../../../ui/Sheet';
import { failure } from '../../settings/shared';
import { useRefreshInvestments } from './api';
import { CHOOSE_FILE, FIELD_LABELS, IMPORT_POSITIONS, NOT_IN_FILE } from './copy';
import { previewLine } from './format';

const FIELDS = ['symbol', 'name', 'shares', 'value', 'cost_basis'] as const;
export type Mapping = Record<(typeof FIELDS)[number], string | null>;
type Preview = {
  needs_mapping: boolean; remembered: boolean; headers: string[]; mapping: Mapping; as_of: string;
  count?: number; total_cents?: number; balance_cents?: number | null; difference_cents?: number | null;
  positions?: { symbol: string | null; name: string; value_cents: number }[];
};
export type Saved = { count: number; total_cents: number; as_of: string; first: boolean };

function body(file: File, mapping: Mapping | null, asOf: string | null): FormData {
  const f = new FormData();
  f.append('file', file);
  if (mapping) f.append('mapping', JSON.stringify(mapping));
  if (asOf) f.append('as_of', asOf);
  return f;
}

/** Import positions (investment views spec, From a positions CSV), in its own chunk. Choose the file; the first time
 *  from a place, confirm the guessed columns (a remembered one skips that); check the total against the balance; save.
 *  The file goes to the vault, which reads it in memory and keeps only its name. The date is the vault's today unless the
 *  person changes it: the browser's own date may be a day ahead of the vault's. */
export default function PositionsImport({ accountId, onClose, onSaved }: { accountId: number; onClose: () => void; onSaved: (r: Saved) => void }) {
  const refresh = useRefreshInvestments();
  const [file, setFile] = useState<File | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<Mapping | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [latest, setLatest] = useState<string | null>(null); // the first preview's day: the cap stays put after a re-preview
  const asOf = chosen ?? preview?.as_of ?? null;

  async function look(f: File, m: Mapping | null) {
    setBusy(true);
    setError('');
    try {
      const p = await api<Preview>(`/api/accounts/${accountId}/positions/preview`, { method: 'POST', body: body(f, m, chosen) });
      setPreview(p);
      setLatest((l) => l ?? p.as_of);
      setMapping(p.mapping);
    } catch (e) {
      setError(failure(e));
    } finally {
      setBusy(false);
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!file || !mapping) return;
    setBusy(true);
    setError('');
    try {
      const r = await api<Saved>(`/api/accounts/${accountId}/positions`, { method: 'POST', body: body(file, mapping, asOf) });
      await refresh();
      onSaved(r);
    } catch (err) {
      setError(failure(err));
      setBusy(false);
    }
  }

  const ready = preview !== null && !preview.needs_mapping;
  return (
    <Sheet open onClose={onClose} title={IMPORT_POSITIONS} className="posimp">
      <form className="sheet-form" onSubmit={save}>
        <Field label={CHOOSE_FILE}>
          <input type="file" accept=".csv,text/csv" onChange={(e) => {
            const f = e.target.files?.[0] ?? null;
            setFile(f);
            setPreview(null);
            if (f) void look(f, null);
          }} />
        </Field>
        {preview?.needs_mapping && mapping && (
          <fieldset className="posimp__map">
            {FIELDS.map((k) => (
              <Field key={k} label={FIELD_LABELS[k]}>
                <select value={mapping[k] ?? ''} onChange={(e) => setMapping({ ...mapping, [k]: e.target.value || null })}>
                  <option value="">{NOT_IN_FILE}</option>
                  {preview.headers.map((h, i) => <option key={`${h}-${i}`} value={h}>{h}</option>)}
                </select>
              </Field>
            ))}
            <Button onClick={() => { if (file) void look(file, mapping); }} busy={busy} disabled={!mapping.value || !(mapping.symbol || mapping.name)}>{PREVIEW}</Button>
          </fieldset>
        )}
        {ready && (
          <>
            <p className="posimp__line" data-testid="positions-preview">{previewLine(preview)}</p>
            <table className="posimp__table">
              <tbody>{(preview.positions ?? []).slice(0, 8).map((p, i) => <tr key={i}><th scope="row">{p.symbol ?? p.name}</th><td>{dollars(p.value_cents)}</td></tr>)}</tbody>
            </table>
          </>
        )}
        {preview && asOf && <Field label={AS_OF}><input type="date" value={asOf} max={latest ?? preview.as_of} onChange={(e) => setChosen(e.target.value)} /></Field>}
        {error && <Notice tone="error"><p>{error}</p></Notice>}
        {ready && <Button type="submit" busy={busy}>{SAVE}</Button>}
      </form>
    </Sheet>
  );
}
