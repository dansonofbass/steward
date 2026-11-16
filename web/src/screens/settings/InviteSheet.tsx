import { useState, type FormEvent } from 'react';
import { api, json } from '../../api/client';
import type { Role } from '../../api/types';
import { EMAIL, INVITE, INVITE_NAME_HINT, INVITE_SENT, INVITE_SOMEONE, MANAGER_ROLE, MEMBER_ADDED, NAME, ROLE, VIEWER_HINT, VIEWER_ROLE } from '../../lib/copy';
import { Button } from '../../ui/Button';
import { CopyButton } from '../../ui/CopyButton';
import { Field } from '../../ui/Field';
import { Notice } from '../../ui/Notice';
import { Sheet } from '../../ui/Sheet';
import { COPY, DONE, MAIL_OFF_INVITE, SEND_YOURSELF } from './inviteCopy';
import { failure } from './shared';

/** Invite someone to a book: Book members and the first run's extras open it. A lazy chunk: it loads when Book members
 *  opens (or with the welcome), not with the first download (guided setup spec 11).
 *  With email off, an install manager gets the text the invite would have said, to pass on; `onDone('')` closes it
 *  (nothing was sent, so there is no line to show). Anyone else is told plainly. */
export function InviteSheet({ slug, onClose, onDone }: { slug: string; onClose: () => void; onDone: (line: string) => void }) {
  const [email, setEmail] = useState('');
  const [pass, setPass] = useState<{ to: string; text: string } | null>(null);
  const [name, setName] = useState('');
  const [role, setRole] = useState<Role>('viewer');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const r = await api<{ member: { email: string; display_name?: string }; invited: boolean; send_yourself?: string; mail_off?: boolean }>(
        `/api/books/${encodeURIComponent(slug)}/members`, json({ email: email.trim(), display_name: name.trim(), role }));
      if (r.send_yourself) { setPass({ to: email.trim(), text: r.send_yourself }); setBusy(false); return; }
      if (r.mail_off) { onDone(MAIL_OFF_INVITE); return; }
      // The line never says whether the address already had an account: an invited answer names the typed email.
      onDone(r.invited ? INVITE_SENT.replace('{email}', email.trim()) : MEMBER_ADDED.replace('{name}', r.member.display_name ?? r.member.email));
    } catch (err) {
      setError(failure(err));
      setBusy(false);
    }
  }
  if (pass) {
    return (
      <Sheet open onClose={() => onDone('')} title={INVITE_SOMEONE}>
        <div className="sheet-form">
          <p>{SEND_YOURSELF.replace('{email}', pass.to)}</p>
          <textarea readOnly rows={8} value={pass.text} aria-label={SEND_YOURSELF.replace('{email}', pass.to)} onFocus={(e) => e.currentTarget.select()} />
          <div className="member-actions">
            <CopyButton text={pass.text} label={COPY} />
            <Button onClick={() => onDone('')}>{DONE}</Button>
          </div>
        </div>
      </Sheet>
    );
  }
  return (
    <Sheet open onClose={onClose} title={INVITE_SOMEONE}>
      <form className="sheet-form" onSubmit={save}>
        <Field label={EMAIL}><input type="email" autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label={NAME} hint={INVITE_NAME_HINT}><input maxLength={80} value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label={ROLE} hint={VIEWER_HINT}>
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="viewer">{VIEWER_ROLE}</option>
            <option value="manager">{MANAGER_ROLE}</option>
          </select>
        </Field>
        {error && <Notice tone="error">{error}</Notice>}
        <Button type="submit" busy={busy} disabled={!email.trim()}>{INVITE}</Button>
      </form>
    </Sheet>
  );
}

export default InviteSheet;
