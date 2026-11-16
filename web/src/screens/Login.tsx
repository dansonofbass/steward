import { useQueryClient } from '@tanstack/react-query';
import { Fingerprint } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api, ApiError, json } from '../api/client';
import { signInWithPasskey, supported } from '../auth/passkeys';
import { deviceLabel } from '../lib/device';
import { lockoutMinutes } from '../lib/lockout';
import { FORGOT, OR, PASSWORD, SIGN_IN, SIGN_IN_PASSKEY, USERNAME } from '../lib/copy';
import { Button } from '../ui/Button';
import { Field } from '../ui/Field';
import { Notice } from '../ui/Notice';
import { AuthPanel, safeNext } from './AuthPanel';

export default function Login() {
  const [params] = useSearchParams();
  const next = safeNext(params.get('next'));
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState<'passkey' | 'password' | null>(null);
  const [passkeyError, setPasskeyError] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [locked, setLocked] = useState(false);
  const device = deviceLabel(navigator.userAgent);

  // A lockout ends by itself: re-enable the form when the wait is over.
  useEffect(() => {
    if (!locked) return;
    const t = setTimeout(() => setLocked(false), lockoutMinutes(passwordError) * 60_000);
    return () => clearTimeout(t);
  }, [locked, passwordError]);

  function signedIn() {
    queryClient.removeQueries({ queryKey: ['me'] }); // the next screen asks again, so it never sees the old 401
    navigate(next, { replace: true });
  }

  async function withPasskey() {
    setBusy('passkey');
    setPasskeyError('');
    try {
      await signInWithPasskey(device);
      signedIn();
    } catch (e) {
      setPasskeyError(e instanceof ApiError ? e.message : "That didn't finish. Try again.");
      setBusy(null);
    }
  }

  async function withPassword(e: FormEvent) {
    e.preventDefault();
    setBusy('password');
    setPasswordError('');
    try {
      await api('/api/auth/login', json({ username, password, device_label: device }));
      signedIn();
    } catch (err) {
      setPasswordError(err instanceof ApiError ? err.message : "That didn't finish. Try again.");
      setLocked(err instanceof ApiError && err.status === 423);
      setBusy(null);
    }
  }

  return (
    <AuthPanel>
      {supported() && (
        <>
          <div className="login__passkey">
            <Button className="btn--block" icon={Fingerprint} busy={busy === 'passkey'} onClick={withPasskey}>{SIGN_IN_PASSKEY}</Button>
            {passkeyError && <Notice tone="error">{passkeyError}</Notice>}
          </div>
          <p className="or">{OR}</p>
        </>
      )}
      <form onSubmit={withPassword}>
        <Field label={USERNAME}>
          <input autoComplete="username" autoCapitalize="none" value={username} onChange={(e) => { setUsername(e.target.value); setLocked(false); }} />
        </Field>
        <Field label={PASSWORD} error={passwordError} notice>
          <input type="password" autoComplete="current-password" value={password} disabled={locked}
            onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Button type="submit" variant="quiet" className="btn--block" busy={busy === 'password'} disabled={locked}>{SIGN_IN}</Button>
        <Link className="login__forgot" to="/forgot">{FORGOT}</Link>
      </form>
    </AuthPanel>
  );
}
