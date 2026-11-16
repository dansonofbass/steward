import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Button } from '../../ui/Button';
import { Field } from '../../ui/Field';
import { pairCode } from './api';
import { CODE, PAIR } from './copy';
import './ready.css';

/** What the gateway does with a typed code: upper-case it and keep only letters and digits. */
export const normalizeCode = (raw: string) => raw.toUpperCase().replace(/[^A-Z0-9]/g, '');

/** The six characters `steward-gateway pair` shows. The server's words are shown as they come: no celebration. */
export function PairForm({ onPaired }: { onPaired?: () => void }) {
  const qc = useQueryClient();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [line, setLine] = useState<string | null>(null);
  async function submit() {
    setBusy(true);
    setError(null);
    setLine(null);
    try {
      const r = await pairCode(normalizeCode(code));
      setLine(r.line);
      setCode('');
      void qc.invalidateQueries({ queryKey: ['ready'] });
      void qc.invalidateQueries({ queryKey: ['chat'] });
      onPaired?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="ready__form" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
      <Field label={CODE} error={error}>
        <input value={code} onChange={(e) => setCode(e.target.value)} autoCapitalize="characters" autoComplete="off" spellCheck={false} maxLength={24} />
      </Field>
      <div className="ready__check"><Button type="submit" busy={busy} disabled={!normalizeCode(code)}>{PAIR}</Button></div>
      {line && <p>{line}</p>}
    </form>
  );
}
