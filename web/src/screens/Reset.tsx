import { useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, ApiError, json } from '../api/client';
import { CHANGE_PASSWORD, CHOOSE_PASSWORD, INVITE_LEDE, NEW_PASSWORD, PASSWORD_CHANGED, RESET_LEDE, SIGN_IN } from '../lib/copy';
import { Button } from '../ui/Button';
import { Field } from '../ui/Field';
import { Notice } from '../ui/Notice';
import { AuthPanel } from './AuthPanel';

export default function Reset() {
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const invite = params.get('invite') === '1';
  const heading = invite ? CHOOSE_PASSWORD : CHANGE_PASSWORD;
  const lede = invite ? INVITE_LEDE : RESET_LEDE;
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await api('/api/auth/reset', json({ token, password }));
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That didn't finish. Try again.");
    }
    setBusy(false);
  }

  if (done) {
    return (
      <AuthPanel heading={heading} lede={lede}>
        <Notice>{PASSWORD_CHANGED}</Notice>
        <Link className="login__forgot" to="/login">{SIGN_IN}</Link>
      </AuthPanel>
    );
  }
  return (
    <AuthPanel heading={heading} lede={lede}>
      <form onSubmit={submit}>
        <Field label={NEW_PASSWORD}>
          <input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {error && <Notice tone="error">{error}</Notice>}
        <Button type="submit" className="btn--block" busy={busy}>{heading}</Button>
      </form>
    </AuthPanel>
  );
}
