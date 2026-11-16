import { useQueryClient } from '@tanstack/react-query';
import { KeyRound, Trash2, User, UserPlus } from 'lucide-react';
import { Suspense, useEffect, useState, type FormEvent } from 'react';
import { useLocation } from 'react-router-dom';
import { api, del, json, patch } from '../../api/client';
import { useMe, useMembers, useUsers } from '../../api/hooks';
import type { InvitedRow, Member, Role } from '../../api/types';
import { useBook, useCanEdit } from '../../book/BookContext';
import {
  BOOK_ADDED, CANCEL, CANCEL_INVITE, CANCEL_INVITE_BODY, CANCEL_INVITE_TITLE, INVITED, INVITE_CANCELLED, INVITE_SOMEONE,
  KEEP_IT, MAKE_MANAGER, MAKE_VIEWER, MANAGER_ROLE, ME_REMOVED, MEMBER_REMOVED, NEW_PASSWORD, PEOPLE, SIGN_INS, REMOVE, REMOVE_FROM, REMOVE_FROM_BODY, REMOVE_ME, REMOVE_ME_BODY,
  REMOVE_ME_TITLE, RESET_OTHER_DONE, RESET_OTHER_LEDE, ROLE, ROLE_MANAGER_BODY, ROLE_ME_TITLE, ROLE_ME_VIEWER_BODY, ROLE_TITLE, ROLE_VIEWER_BODY, S_BOOK_MEMBERS, SAVE,
  VIEWER_ROLE, YOUR_PASSWORD, YOUR_PASSWORD_HINT,
} from '../../lib/copy';
import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import { ConfirmSheet } from '../../ui/ConfirmSheet';
import { Field } from '../../ui/Field';
import { Notice } from '../../ui/Notice';
import { Sheet } from '../../ui/Sheet';
import { Skeleton } from '../../ui/Skeleton';
import { lazyScreen } from '../../lib/lazyScreen';
import { BACK_TO_OPENER, useRemoval } from '../../lib/useRemoval';
import { RemovalLine } from '../../ui/RemovalLine';
import { failure } from './shared';
import './members.css';

// The invite sheet (and its email-off view, D9) is a lazy chunk; Book members preloads it when it opens.
const InviteSheet = lazyScreen(() => import('./InviteSheet'));

const roleWord = (r: Role) => (r === 'manager' ? MANAGER_ROLE : VIEWER_ROLE);
const isInvited = (m: Member | InvitedRow): m is InvitedRow => m.user_id === null;

/** The confirmation for a role change: the title names the person (or "yourself") and the book; the body says what the role can do. */
function roleAsk(m: Member, role: Role, book: string, me: boolean): { title: string; body: string } {
  const word = roleWord(role).toLowerCase();
  const title = (me ? ROLE_ME_TITLE : ROLE_TITLE.replace('{name}', m.display_name)).replace('{role}', word).replace('{book}', book);
  const body = (me && role === 'viewer' ? ROLE_ME_VIEWER_BODY : role === 'manager' ? ROLE_MANAGER_BODY : ROLE_VIEWER_BODY)
    .replace('{name}', m.display_name).replaceAll('{book}', book);
  return { title, body };
}

function ResetSheet({ person, onClose, onDone }: { person: { id: number; display_name: string }; onClose: () => void; onDone: () => void }) {
  const [current, setCurrent] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await api(`/api/users/${person.id}/reset-password`, json({ current_password: current, password }));
      onDone();
    } catch (err) {
      setError(failure(err));
      setBusy(false);
    }
  }

  return (
    <Sheet open onClose={onClose} title={`Reset ${person.display_name}'s password`}>
      <form className="device-form" onSubmit={save}>
        <p>{RESET_OTHER_LEDE.replace('{name}', person.display_name)}</p>
        <Field label={NEW_PASSWORD}>
          <input type="password" value={password} autoComplete="new-password" onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Field label={YOUR_PASSWORD} hint={YOUR_PASSWORD_HINT}>
          <input type="password" value={current} autoComplete="current-password" onChange={(e) => setCurrent(e.target.value)} />
        </Field>
        {error && <Notice tone="error">{error}</Notice>}
        <Button type="submit" busy={busy} disabled={!password || !current}>{SAVE}</Button>
      </form>
    </Sheet>
  );
}

function People() {
  const users = useUsers();
  const me = useMe();
  const [resetting, setResetting] = useState<{ id: number; display_name: string } | null>(null);
  const [done, setDone] = useState('');
  return (
    <>
      <h3 className="subhead">{SIGN_INS}</h3>
      {done && <Notice>{done}</Notice>}
      <Card className="lines">
        {users.isPending && <div className="line"><Skeleton lines={1} /></div>}
        {users.isError && <div className="line"><Notice tone="error">{users.error.message}</Notice></div>}
        {users.data?.users.map((u) => (
          <div className="line" key={u.id}>
            <div className="line__lead">
              <User size={20} aria-hidden="true" />
              <div className="line__main"><span>{u.display_name}</span><span className="small muted">{u.username}</span></div>
            </div>
            {u.id === me.data?.user.id
              ? <span className="small muted">You</span>
              : u.can_reset && <Button variant="quiet" icon={KeyRound} onClick={() => { setDone(''); setResetting(u); }}>{`Reset ${u.display_name}'s password`}</Button>}
          </div>
        ))}
      </Card>
      {resetting && <ResetSheet person={resetting} onClose={() => setResetting(null)}
        onDone={() => { setDone(RESET_OTHER_DONE.replace('{name}', resetting.display_name)); setResetting(null); }} />}
    </>
  );
}

export default function Members() {
  const book = useBook();
  const slug = book?.slug ?? 'ours';
  const members = useMembers(slug);
  const me = useMe();
  const canEdit = useCanEdit();
  const qc = useQueryClient();
  const loc = useLocation();
  const added = (loc.state as { added?: string } | null)?.added;
  const [line, setLine] = useState(added ? BOOK_ADDED.replace('{name}', added) : '');
  // A removal or a cancelled invite says what went, and focus goes to People rather than the gone row's button (THO-1).
  const removal = useRemoval();
  const [error, setError] = useState('');
  const [inviting, setInviting] = useState(false);
  const [removing, setRemoving] = useState<Member | null>(null);
  // A role change waits for a second click; the select itself stays on the saved role until then.
  const [rerole, setRerole] = useState<{ m: Member; role: Role } | null>(null);
  const [cancelling, setCancelling] = useState<InvitedRow | null>(null);
  const [busy, setBusy] = useState<number | string | null>(null);
  const refresh = () => Promise.all(['members', 'me', 'users'].map((k) => qc.invalidateQueries({ queryKey: [k] })));
  const base = `/api/books/${encodeURIComponent(slug)}/members`;
  const isMe = (m: Member) => m.user_id === me.data?.user.id;
  useEffect(() => { if (canEdit) void InviteSheet.preload(); }, [canEdit]);   // ready before Invite someone is pressed

  async function changeRole(m: Member, role: Role) {
    setError('');
    setLine('');
    removal.clear();
    setBusy(m.user_id);
    try { await api(`${base}/${m.user_id}`, patch({ role })); await refresh(); } catch (e) { setError(failure(e)); }
    setBusy(null);
    setRerole(null);
  }
  async function remove(m: Member) {
    setError('');
    setLine('');
    setBusy(m.user_id);
    try {
      await api(`${base}/${m.user_id}`, del());
      await refresh();
      const bookName = book?.name ?? '';
      if (isMe(m)) removal.removed(ME_REMOVED.replace('{book}', bookName));
      else removal.removed(MEMBER_REMOVED.replace('{name}', m.display_name).replace('{book}', bookName));
    } catch (e) { setError(failure(e)); }
    setBusy(null);
    setRemoving(null);
  }
  async function cancelInvite(r: InvitedRow) {
    setError('');
    setLine('');
    setBusy(r.invite_id);
    try {
      await api(`/api/books/${encodeURIComponent(slug)}/invites/${encodeURIComponent(r.invite_id)}`, del());
      await refresh();
      removal.removed(INVITE_CANCELLED.replace('{email}', r.email));
    } catch (e) { setError(failure(e)); }
    setBusy(null);
    setCancelling(null);
  }

  const bookName = book?.name ?? '';
  const ask = rerole && roleAsk(rerole.m, rerole.role, bookName, isMe(rerole.m));
  return (
    <>
      <section className="spage" aria-labelledby="members-h">
        <h2 id="members-h">{S_BOOK_MEMBERS}</h2>
        {line && <Notice>{line}</Notice>}
        <RemovalLine removal={removal} />
        <div className="section-head">
          <h3 className="subhead" ref={removal.anchor} tabIndex={-1}>{PEOPLE}</h3>
          {canEdit && <Button icon={UserPlus} onClick={() => { setLine(''); removal.clear(); setInviting(true); }}>{INVITE_SOMEONE}</Button>}
        </div>
        {error && <Notice tone="error">{error}</Notice>}
        <Card className="lines">
          {members.isPending && <div className="line"><Skeleton lines={1} /></div>}
          {members.isError && <div className="line"><Notice tone="error">{members.error.message}</Notice></div>}
          {members.data?.members.map((m) => isInvited(m) ? (
            <div className="line" key={`invite-${m.invite_id}`}>
              <div className="line__main"><span>{m.email}</span><span className="small muted">{INVITED}</span></div>
              {canEdit && (
                <div className="member-actions">
                  <Button variant="quiet" aria-label={`${CANCEL} ${m.email}`} busy={busy === m.invite_id} onClick={() => setCancelling(m)}>{CANCEL}</Button>
                </div>
              )}
            </div>
          ) : (
            <div className="line" key={m.user_id}>
              <div className="line__main"><span>{m.display_name}</span><span className="small muted">{m.email}</span></div>
              {canEdit ? (
                <div className="member-actions">
                  <select aria-label={`${ROLE}, ${m.display_name}`} value={m.role} disabled={busy === m.user_id}
                    onChange={(e) => setRerole({ m, role: e.target.value as Role })}>
                    <option value="manager">{MANAGER_ROLE}</option>
                    <option value="viewer">{VIEWER_ROLE}</option>
                  </select>
                  <Button variant="danger" icon={Trash2} aria-label={`${REMOVE} ${m.display_name}`} onClick={() => setRemoving(m)}>{REMOVE}</Button>
                </div>
              ) : <span className="small muted">{roleWord(m.role)}</span>}
            </div>
          ))}
        </Card>
        <People />
      </section>
      {inviting && <Suspense fallback={null}><InviteSheet slug={slug} onClose={() => setInviting(false)} onDone={(l) => { setLine(l); setInviting(false); void refresh(); }} /></Suspense>}
      {removing && book && (isMe(removing) ? (
        // Removing yourself names the book on the title and on the button itself, so the second click can't be mistaken.
        <ConfirmSheet open onClose={() => setRemoving(null)} title={REMOVE_ME_TITLE.replace('{book}', book.name)}
          body={REMOVE_ME_BODY.replace('{book}', book.name)} action={REMOVE_ME.replace('{book}', book.name)} icon={Trash2}
          busy={busy === removing.user_id} onConfirm={() => void remove(removing)} returnTo={removal.returnTo} />
      ) : (
        <ConfirmSheet open onClose={() => setRemoving(null)} title={REMOVE_FROM.replace('{name}', removing.display_name).replace('{book}', book.name)}
          body={REMOVE_FROM_BODY.replaceAll('{name}', removing.display_name).replaceAll('{book}', book.name)} action={REMOVE} icon={Trash2}
          busy={busy === removing.user_id} onConfirm={() => void remove(removing)} returnTo={removal.returnTo} />
      ))}
      {rerole && ask && (
        <ConfirmSheet open onClose={() => setRerole(null)} title={ask.title} body={ask.body} variant="primary"
          action={rerole.role === 'manager' ? MAKE_MANAGER : MAKE_VIEWER} busy={busy === rerole.m.user_id} onConfirm={() => void changeRole(rerole.m, rerole.role)}
          returnTo={BACK_TO_OPENER} />
      )}
      {cancelling && (
        <ConfirmSheet open onClose={() => setCancelling(null)} title={CANCEL_INVITE_TITLE.replace('{email}', cancelling.email)} body={CANCEL_INVITE_BODY}
          action={CANCEL_INVITE} cancel={KEEP_IT} busy={busy === cancelling.invite_id} onConfirm={() => void cancelInvite(cancelling)}
          returnTo={removal.returnTo} />
      )}
    </>
  );
}
