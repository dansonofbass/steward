import { Link as LinkIcon } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { api, json } from '../../api/client';
import type { LinkResult } from '../../api/types';
import { LINK, SETUP_TOKEN, SETUP_TOKEN_HINT } from '../../lib/copy';
import { Button } from '../../ui/Button';
import { Field } from '../../ui/Field';
import { Notice } from '../../ui/Notice';
import { failure } from './shared';

/** The SimpleFIN setup-token form: Settings' Banks card and the first run's "Link your banks" both use it. It owns the
 *  token, the busy state and its own error; a link that went through is handed to `onLinked`. */
export function LinkForm({ onLinked }: { onLinked: (r: LinkResult) => void }) {
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function link(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const r = await api<LinkResult>('/api/simplefin/link', json({ setup_token: token.trim() }));
      setToken('');
      onLinked(r);
    } catch (err) {
      setError(failure(err));
    }
    setBusy(false);
  }

  return (
    <>
      <form className="form-row" onSubmit={link}>
        <Field label={SETUP_TOKEN} hint={SETUP_TOKEN_HINT}>
          <textarea rows={2} value={token} autoComplete="off" spellCheck={false} onChange={(e) => setToken(e.target.value)} />
        </Field>
        <Button type="submit" icon={LinkIcon} busy={busy} disabled={!token.trim()}>{LINK}</Button>
      </form>
      {error && <Notice tone="error">{error}</Notice>}
    </>
  );
}
