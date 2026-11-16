import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiError, json } from '../api/client';
import { BACK_TO_SIGN_IN, FORGOT, FORGOT_LEDE, SEND_LINK, USERNAME_OR_EMAIL } from '../lib/copy';
import { Button } from '../ui/Button';
import { Field } from '../ui/Field';
import { Notice } from '../ui/Notice';
import { AuthPanel } from './AuthPanel';

export default function Forgot() {
  const [who, setWho] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const r = await api<{ message: string }>('/api/auth/forgot', json({ username: who }));
      setMessage(r.message);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That didn't finish. Try again.");
    }
    setBusy(false);
  }

  return (
    <AuthPanel heading={FORGOT} lede={FORGOT_LEDE}>
      <form onSubmit={submit}>
        <Field label={USERNAME_OR_EMAIL}>
          <input autoComplete="username" autoCapitalize="none" value={who} onChange={(e) => setWho(e.target.value)} />
        </Field>
        {message && <Notice>{message}</Notice>}
        {error && <Notice tone="error">{error}</Notice>}
        <Button type="submit" className="btn--block" busy={busy}>{SEND_LINK}</Button>
        <Link className="login__forgot" to="/login">{BACK_TO_SIGN_IN}</Link>
      </form>
    </AuthPanel>
  );
}
