import { useQueryClient } from '@tanstack/react-query';
import { Fingerprint, LogOut, Monitor, Plus, Smartphone, Trash2 } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, del, json } from '../../api/client';
import { useMe, usePasskeys, useSessions } from '../../api/hooks';
import type { Passkey, Session } from '../../api/types';
import { registerThisDevice } from '../../auth/passkeys';
import { dateLabelFromIso, localYmd, relativeDays } from '../../lib/format';
import { deviceName } from '../../lib/device';
import { useRemoval } from '../../lib/useRemoval';
import {
  ADD_THIS_DEVICE, ADDED, CHANGE_MY_PASSWORD, CURRENT_PASSWORD, DEVICE_SIGNED_OUT, LAST_SEEN, MY_PASSWORD_CHANGED, NEW_PASSWORD, NAME_THIS_DEVICE, NO_PASSKEYS, PASSKEY_REMOVED, PASSKEYS, REMOVE,
  REMOVE_PASSKEY_BODY, REMOVE_PASSKEY_TITLE, SAVE, SIGN_IN_AND_DEVICES, SIGN_OUT, SIGN_OUT_DEVICE_BODY, SIGN_OUT_DEVICE_TITLE, SIGN_OUT_HERE_BODY, SIGN_OUT_HERE_TITLE,
  SIGNED_IN_DEVICES, THIS_DEVICE, YOUR_PASSWORD, YOUR_PASSWORD_HINT,
} from '../../lib/copy';
import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import { ConfirmSheet } from '../../ui/ConfirmSheet';
import { Field } from '../../ui/Field';
import { Notice } from '../../ui/Notice';
import { RemovalLine } from '../../ui/RemovalLine';
import { Sheet } from '../../ui/Sheet';
import { Skeleton } from '../../ui/Skeleton';
import { forgetPersonPrefs } from '../../lib/celebrations';
import { failure } from '../settings/shared';
import './SignInDevices.css';


function AddDevice({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [label, setLabel] = useState<string>(() => deviceName(navigator.userAgent));
  const [current, setCurrent] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await registerThisDevice(label.trim(), current);
      await queryClient.invalidateQueries({ queryKey: ['passkeys'] });
      onClose();
    } catch (err) {
      setError(failure(err));
    }
    setBusy(false);
  }

  return (
    <Sheet open={open} onClose={onClose} title={ADD_THIS_DEVICE}>
      <form className="device-form" onSubmit={save}>
        <Field label={NAME_THIS_DEVICE}>
          <input value={label} maxLength={80} onChange={(e) => setLabel(e.target.value)} autoComplete="off" />
        </Field>
        <Field label={YOUR_PASSWORD} hint={YOUR_PASSWORD_HINT}>
          <input type="password" value={current} autoComplete="current-password" onChange={(e) => setCurrent(e.target.value)} />
        </Field>
        {error && <Notice tone="error">{error}</Notice>}
        <Button type="submit" busy={busy} disabled={!current}>{SAVE}</Button>
      </form>
    </Sheet>
  );
}

function Passkeys() {
  const queryClient = useQueryClient();
  const passkeys = usePasskeys();
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState('');
  const [removing, setRemoving] = useState<number | null>(null);
  const [asking, setAsking] = useState<Passkey | null>(null);
  const removal = useRemoval();

  async function remove(p: Passkey) {
    setError('');
    removal.clear();
    setRemoving(p.id);
    try {
      await api(`/api/auth/passkeys/${p.id}`, del());
      await queryClient.invalidateQueries({ queryKey: ['passkeys'] });
      removal.removed(PASSKEY_REMOVED.replace('{label}', p.label)); // the row is gone; focus goes to the heading
    } catch (e) {
      setError(failure(e));
    }
    setRemoving(null);
    setAsking(null);
  }

  const rows = passkeys.data?.passkeys ?? [];
  return (
    <>
      <div className="section-head">
        <h3 className="subhead" ref={removal.anchor} tabIndex={-1}>{PASSKEYS}</h3>
        <Button variant="quiet" icon={Plus} onClick={() => { removal.clear(); setAdding(true); }}>{ADD_THIS_DEVICE}</Button>
      </div>
      <RemovalLine removal={removal} />
      {error && <Notice tone="error">{error}</Notice>}
      <Card className="lines">
        {passkeys.isPending && <div className="line"><Skeleton lines={1} /></div>}
        {passkeys.isError && <div className="line"><Notice tone="error">{passkeys.error.message}</Notice></div>}
        {passkeys.isSuccess && rows.length === 0 && <div className="line line--empty">{NO_PASSKEYS}</div>}
        {rows.map((p) => (
          <div className="line" key={p.id}>
            <div className="line__lead">
              <Fingerprint size={20} aria-hidden="true" />
              <div className="line__main">
                <span>{p.label}</span>
                <span className="small muted">{ADDED.replace('{date}', dateLabelFromIso(p.created_at, new Date()))}</span>
              </div>
            </div>
            <Button variant="danger" icon={Trash2} aria-label={`${REMOVE} ${p.label}`} busy={removing === p.id} onClick={() => setAsking(p)}>{REMOVE}</Button>
          </div>
        ))}
      </Card>
      {adding && <AddDevice open onClose={() => setAdding(false)} />}
      <ConfirmSheet open={asking !== null} onClose={() => setAsking(null)} title={REMOVE_PASSKEY_TITLE.replace('{label}', asking?.label ?? '')} body={REMOVE_PASSKEY_BODY}
        action={REMOVE} icon={Trash2} busy={asking !== null && removing === asking.id} onConfirm={() => asking && void remove(asking)}
        returnTo={removal.returnTo} />
    </>
  );
}

function Devices() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const me = useMe();
  const sessions = useSessions();
  const [error, setError] = useState('');
  const [leaving, setLeaving] = useState<number | null>(null);
  const [asking, setAsking] = useState<Session | null>(null);
  const removal = useRemoval();
  const currentId = me.data?.session.id;

  async function signOut(s: Session) {
    const id = s.id;
    setError('');
    removal.clear();
    setLeaving(id);
    try {
      if (id === currentId) {
        await api('/api/auth/logout', { method: 'POST' });
        queryClient.clear();
        forgetPersonPrefs(); // as the You menu's Sign out
        navigate('/login', { replace: true });
      } else {
        await api(`/api/auth/sessions/${id}`, del());
        await queryClient.invalidateQueries({ queryKey: ['sessions'] });
        removal.removed(DEVICE_SIGNED_OUT.replace('{device}', s.device_label || 'Browser')); // the row is gone; focus goes to the heading
      }
    } catch (e) {
      setError(failure(e));
    }
    setLeaving(null);
    setAsking(null);
  }
  // Signing out this device and signing out another one are told apart: only the first needs a sign-in afterwards.
  const askHere = asking !== null && asking.id === currentId;

  const rows = sessions.data?.sessions ?? [];
  const today = new Date();
  return (
    <>
      <h3 className="subhead" ref={removal.anchor} tabIndex={-1}>{SIGNED_IN_DEVICES}</h3>
      <RemovalLine removal={removal} />
      {error && <Notice tone="error">{error}</Notice>}
      <Card className="lines">
        {sessions.isPending && <div className="line"><Skeleton lines={1} /></div>}
        {sessions.isError && <div className="line"><Notice tone="error">{sessions.error.message}</Notice></div>}
        {rows.map((s) => {
          const here = s.id === currentId;
          const Icon = /iPhone|iPad|Android/.test(s.device_label) ? Smartphone : Monitor;
          const when = relativeDays(localYmd(s.last_seen_at), today);
          return (
            <div className="line" key={s.id}>
              <div className="line__lead">
                <Icon size={20} aria-hidden="true" />
                <div className="line__main">
                  <span>{s.device_label || 'Browser'}</span>
                  <span className="small muted">{here ? `${THIS_DEVICE} · ${when}` : LAST_SEEN.replace('{when}', when)}</span>
                </div>
              </div>
              <Button variant="quiet" icon={LogOut} busy={leaving === s.id} aria-label={`${SIGN_OUT}, ${s.device_label || 'Browser'}`} onClick={() => setAsking(s)}>{SIGN_OUT}</Button>
            </div>
          );
        })}
      </Card>
      <ConfirmSheet open={asking !== null} onClose={() => setAsking(null)}
        title={askHere ? SIGN_OUT_HERE_TITLE : SIGN_OUT_DEVICE_TITLE.replace('{device}', asking?.device_label || 'Browser')}
        body={askHere ? SIGN_OUT_HERE_BODY : SIGN_OUT_DEVICE_BODY}
        action={SIGN_OUT} icon={LogOut} busy={asking !== null && leaving === asking.id} onConfirm={() => asking && void signOut(asking)}
        returnTo={removal.returnTo} />
    </>
  );
}

function ChangeMine() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    setDone(false);
    try {
      await api('/api/auth/password', json({ current_password: current, new_password: next }));
      setCurrent('');
      setNext('');
      setDone(true);
    } catch (err) {
      setError(failure(err));
    }
    setBusy(false);
  }

  return (
    <form className="card device-form" onSubmit={save}>
      <h3 className="subhead">{CHANGE_MY_PASSWORD}</h3>
      <Field label={CURRENT_PASSWORD}><input type="password" value={current} autoComplete="current-password" onChange={(e) => setCurrent(e.target.value)} /></Field>
      <Field label={NEW_PASSWORD} error={error}><input type="password" value={next} autoComplete="new-password" onChange={(e) => setNext(e.target.value)} /></Field>
      <div className="row-actions"><Button type="submit" busy={busy} disabled={!current || !next}>{CHANGE_MY_PASSWORD}</Button></div>
      {done && <Notice>{MY_PASSWORD_CHANGED}</Notice>}
    </form>
  );
}

export default function SignInDevices() {
  return (
    <div className="screen">
      <h1>{SIGN_IN_AND_DEVICES}</h1>
      <div className="spage">
        <ChangeMine />
        <Passkeys />
        <Devices />
      </div>
    </div>
  );
}
