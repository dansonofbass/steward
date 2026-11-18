import { useQueryClient } from '@tanstack/react-query';
import { Fingerprint } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api, ApiError, json } from '../api/client';
import { offerPasskeysInAutofill, signInWithPasskey, supported } from '../auth/passkeys';
import { deviceLabel } from '../lib/device';
import { FORGOT, OR, PASSKEY_STILL_WORKS, PASSWORD, PAUSED_SIGN_IN, SIGN_IN, SIGN_IN_PASSKEY, USERNAME } from '../lib/copy';
import { Button } from '../ui/Button';
import { Field } from '../ui/Field';
import { Notice } from '../ui/Notice';
import { AuthPanel, safeNext } from './AuthPanel';

const LOCK_AFTER = 5;
const nameKey = (name: string) => name.trim().toLowerCase();

export default function Login() {
  const [params] = useSearchParams();
  const next = safeNext(params.get('next'));
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  // 'autofill': a passkey picked in the username box is with the server, so neither button may start another sign-in.
  const [busy, setBusy] = useState<'passkey' | 'password' | 'autofill' | null>(null);
  const [passkeyError, setPasskeyError] = useState('');
  const [passwordError, setPasswordError] = useState('');
  // Issue #7: a lock answers exactly as a wrong password does, so the server never says "locked". The page counts the
  // wrong answers for this username and says what five do (the server's LOCK_AFTER, per device and account). Retyping
  // the same name keeps the count, since the server's lock is still there.
  const [misses, setMisses] = useState({ name: '', count: 0 });
  const paused = misses.count >= LOCK_AFTER && misses.name === nameKey(username);
  const device = deviceLabel(navigator.userAgent);

  function signedIn() {
    queryClient.removeQueries({ queryKey: ['me'] }); // the next screen asks again, so it never sees the old 401
    navigate(next, { replace: true });
  }
  const signedInRef = useRef(signedIn);
  signedInRef.current = signedIn;

  // Issue #13: while the page is open, the username box's autofill offers this site's passkeys too (conditional
  // mediation). The offer pauses while the button's prompt or a password try is under way and stops when the page
  // closes. Starting it again keeps the last start time, so the options budget's minimum gap holds across restarts.
  const autofill = useRef<AbortController | null>(null);
  const lastStart = useRef(-Infinity);
  const open = useRef(false);
  function offerAutofill() {
    if (!supported() || !open.current) return;
    autofill.current?.abort();
    const stop = new AbortController();
    autofill.current = stop;
    void offerPasskeysInAutofill(device, stop.signal, {
      onRefused: (e) => setPasskeyError(e.message),
      checking: (on) => setBusy(on ? 'autofill' : null),
      lastStart,
    }).then((user) => {
      // A pick the server accepted has made a session, even if the offer was stopped while it was checked.
      if (user && open.current) signedInRef.current();
    });
  }
  const offerRef = useRef(offerAutofill);
  offerRef.current = offerAutofill;
  useEffect(() => {
    open.current = true;
    offerRef.current();
    return () => { open.current = false; autofill.current?.abort(); };
  }, []);

  async function withPasskey() {
    autofill.current?.abort();
    setBusy('passkey');
    setPasskeyError('');
    try {
      await signInWithPasskey(device);
      signedIn();
    } catch (e) {
      setPasskeyError(e instanceof ApiError ? e.message : "That didn't finish. Try again.");
      setBusy(null);
      offerAutofill();
    }
  }

  async function withPassword(e: FormEvent) {
    e.preventDefault();
    if (busy === 'autofill') return;   // a submit that gets past the disabled button
    autofill.current?.abort();
    setBusy('password');
    setPasswordError('');
    try {
      await api('/api/auth/login', json({ username, password, device_label: device }));
      signedIn();
    } catch (err) {
      setPasswordError(err instanceof ApiError ? err.message : "That didn't finish. Try again.");
      if (err instanceof ApiError && err.status === 401) {
        const name = nameKey(username);
        setMisses((m) => ({ name, count: m.name === name ? m.count + 1 : 1 }));
      }
      setBusy(null);
      offerAutofill();
    }
  }

  return (
    <AuthPanel>
      {supported() && (
        <>
          <div className="login__passkey">
            <Button className="btn--block" icon={Fingerprint} busy={busy === 'passkey' || busy === 'autofill'} onClick={withPasskey}>{SIGN_IN_PASSKEY}</Button>
            {passkeyError && <Notice tone="error">{passkeyError}</Notice>}
          </div>
          <p className="or">{OR}</p>
        </>
      )}
      <form onSubmit={withPassword}>
        <Field label={USERNAME}>
          <input autoComplete="username webauthn" autoCapitalize="none" spellCheck={false} required value={username}
            onChange={(e) => setUsername(e.target.value)} />
        </Field>
        <Field label={PASSWORD} error={passwordError} notice>
          <input type="password" autoComplete="current-password" value={password}
            onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {paused && <Notice>{supported() ? `${PAUSED_SIGN_IN} ${PASSKEY_STILL_WORKS}` : PAUSED_SIGN_IN}</Notice>}
        <Button type="submit" variant="quiet" className="btn--block" busy={busy === 'password'} disabled={busy === 'autofill'}>{SIGN_IN}</Button>
        <Link className="login__forgot" to="/forgot">{FORGOT}</Link>
      </form>
    </AuthPanel>
  );
}
