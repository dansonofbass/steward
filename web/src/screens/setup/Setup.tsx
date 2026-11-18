import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type FormEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { api, ApiError, json } from '../../api/client';
import { registerThisDevice, supported } from '../../auth/passkeys';
import { EMAIL, PASSWORD, USERNAME } from '../../lib/copy';
import { deviceLabel } from '../../lib/device';
import { Button } from '../../ui/Button';
import { Field } from '../../ui/Field';
import { Notice } from '../../ui/Notice';
import { AuthPanel } from '../AuthPanel';
import * as C from './copy';

type Stage = 'checking' | 'form' | 'gone' | 'passkey';

/** The page `steward setup`'s one-time link opens (release spec 2026-11-05, section 6). The token rides in the
 *  fragment, so the browser never sends it in an address; the page reads it once, takes it out of the address bar and
 *  history, and sends it only in a JSON body. After the account, it offers a passkey, then lands on Home (guided setup
 *  spec 1.3, item 4). */
export default function Setup() {
  const loc = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [token] = useState(() => loc.hash.replace(/^#/, ''));
  const [stage, setStage] = useState<Stage>(token ? 'checking' : 'gone');
  const [gone, setGone] = useState(token ? '' : C.NO_LINK);
  const [name, setName] = useState('');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const device = deviceLabel(navigator.userAgent);

  useEffect(() => {
    if (loc.hash) navigate({ pathname: loc.pathname, search: loc.search, hash: '' }, { replace: true });
  }, [loc.hash, loc.pathname, loc.search, navigate]);

  useEffect(() => {
    if (!token) return;
    let live = true;
    api('/api/setup/check', json({ token })).then(
      () => { if (live) setStage('form'); },
      (e: unknown) => { if (live) { setGone(e instanceof ApiError ? e.message : C.LINK_GONE); setStage('gone'); } },
    );
    return () => { live = false; };
  }, [token]);

  function home() {
    qc.removeQueries({ queryKey: ['me'] });   // Home asks again, so it never sees an answer from before the account
    navigate('/', { replace: true });
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await api('/api/setup', json({ token, display_name: name, username, email, password, device_label: device }));
      if (supported()) { setStage('passkey'); setBusy(false); } else home();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : C.DIDNT_FINISH);
      setBusy(false);
    }
  }

  async function addPasskey() {
    setBusy(true);
    setError('');
    try {
      await registerThisDevice(device, password);
      home();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : C.DIDNT_FINISH);
      setBusy(false);
    }
  }

  if (stage === 'checking') return <AuthPanel heading={C.HEADING} lede={C.LEDE}><div aria-busy="true" /></AuthPanel>;
  if (stage === 'gone') return <AuthPanel heading={C.HEADING} lede={C.LEDE}><Notice tone="error"><WithCommand text={gone} /></Notice></AuthPanel>;
  if (stage === 'passkey') {
    return (
      <AuthPanel heading={C.PASSKEY_HEADING} lede={C.PASSKEY_LEDE}>
        {error && <Notice tone="error">{error}</Notice>}
        <Button className="btn--block" busy={busy} onClick={addPasskey}>{C.ADD_PASSKEY}</Button>
        <Button variant="quiet" className="btn--block" onClick={home}>{C.NOT_NOW}</Button>
      </AuthPanel>
    );
  }
  return (
    <AuthPanel heading={C.HEADING} lede={C.LEDE}>
      <form onSubmit={submit}>
        <Field label={C.YOUR_NAME}>
          <input autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label={USERNAME}>
          <input autoComplete="username" autoCapitalize="none" value={username} onChange={(e) => setUsername(e.target.value)} />
        </Field>
        <Field label={EMAIL}>
          <input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label={PASSWORD} hint={C.PASSWORD_HINT}>
          <input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {error && <Notice tone="error">{error}</Notice>}
        <Button type="submit" className="btn--block" busy={busy}>{C.MAKE_ACCOUNT}</Button>
      </form>
    </AuthPanel>
  );
}

/** The words with the setup command, wherever it appears, set as code. */
function WithCommand({ text }: { text: string }) {
  const [before, ...rest] = text.split(C.SETUP_COMMAND);
  if (!rest.length) return <>{text}</>;
  return <>{before}<code>{C.SETUP_COMMAND}</code>{rest.join(C.SETUP_COMMAND)}</>;
}
