import { useQueryClient } from '@tanstack/react-query';
import { Copy, KeyRound } from 'lucide-react';
import { useState } from 'react';
import type { BookSummary } from '../../api/types';
import { useRemoval } from '../../lib/useRemoval';
import { Button } from '../../ui/Button';
import { ConfirmSheet } from '../../ui/ConfirmSheet';
import { CopyButton } from '../../ui/CopyButton';
import { Notice } from '../../ui/Notice';
import { RemovalLine } from '../../ui/RemovalLine';
import { Sheet } from '../../ui/Sheet';
import { Skeleton } from '../../ui/Skeleton';
import { failure } from '../settings/shared';
import { fill } from './askApi';
import * as C from './copy';
import { issueGrant, revokeGrant, useGrants, type Grant, type Issued } from './grantsApi';

/** One book's Claude Code grants: the list, Issue (a manager, for themself) and Revoke (a manager or the grant's person). */
export function ClaudeCodeCard({ book }: { book: BookSummary }) {
  const q = useGrants(book.slug);
  const qc = useQueryClient();
  const [issuing, setIssuing] = useState(false);
  const [issued, setIssued] = useState<Issued | null>(null);
  const [revoking, setRevoking] = useState<Grant | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A revoked grant leaves the list, and the list can go with it, so the line holds focus (THO-1).
  const removal = useRemoval();
  if (q.isPending) return <div className="chat-cc"><Skeleton lines={2} /></div>;
  if (q.isError) return <Notice tone="error">{q.error.message}</Notice>;
  const g = q.data;
  const refresh = () => qc.invalidateQueries({ queryKey: ['chat', 'grants-of', book.slug] });

  function closeIssue() {
    setIssuing(false);
    setIssued(null);
    setError(null);
  }
  async function issue() {
    setBusy(true);
    setError(null);
    removal.clear();
    try {
      setIssued(await issueGrant(book.slug));
      void refresh();
    } catch (e) {
      setError(failure(e));
    } finally {
      setBusy(false);
    }
  }
  async function revoke() {
    if (!revoking) return;
    setBusy(true);
    setError(null);
    try {
      await revokeGrant(book.slug, revoking.id);
      removal.removed(fill(C.CC_REVOKED, { person: revoking.person, book: book.name }));
      setRevoking(null);
      void refresh();
    } catch (e) {
      setError(failure(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="chat-cc chat__grants">
      <div className="chat-set-row">
        <span className="strong">{book.name}</span>
        {g.can_issue && <Button variant="quiet" icon={KeyRound} onClick={() => setIssuing(true)}>{C.CC_ISSUE}</Button>}
      </div>
      <RemovalLine removal={removal} holdsFocus />
      {g.grants.length === 0 ? <p className="small muted">{C.CC_NONE}</p> : (
        <ul className="plain">
          {g.grants.map((x) => (
            <li key={x.id} className="chat-set-row">
              <span className="stack stack--tight">
                <span>{fill(C.CC_ROW, { person: x.person, by: x.issued_by, day: x.issued })}</span>
                <span className="set-row__sub">{x.line}</span>
              </span>
              {x.can_revoke && <Button variant="quiet" aria-label={fill(C.CC_REVOKE_FOR, { person: x.person })} onClick={() => setRevoking(x)}>{C.CC_REVOKE}</Button>}
            </li>
          ))}
        </ul>
      )}
      {error && !issuing && !revoking && <Notice tone="error">{error}</Notice>}
      <Sheet open={issuing} onClose={closeIssue} title={fill(C.CC_ISSUE_IN, { book: book.name })}>
        {issued ? (
          <div className="sheet-form">
            <p>{C.CC_ONCE}</p>
            <p className="small">{C.CC_RUN}</p>
            <code className="raw chat__grant">{issued.command}</code>
            <code className="raw chat__grant">{issued.grant}</code>
            <div className="row-actions">
              <CopyButton text={issued.grant} label={C.CC_COPY} icon={Copy} variant="primary" />
              <Button variant="quiet" onClick={closeIssue}>{C.CC_DONE}</Button>
            </div>
          </div>
        ) : (
          <div className="sheet-form">
            <p>{C.CC_FOR_YOU}</p>
            <p className="small muted">{fill(C.CC_ISSUE_NOTE, { days: g.days })}</p>
            {error && <Notice tone="error">{error}</Notice>}
            <div className="row-actions">
              <Button icon={KeyRound} busy={busy} onClick={() => void issue()}>{C.CC_ISSUE}</Button>
              <Button variant="quiet" onClick={closeIssue}>{C.CANCEL}</Button>
            </div>
          </div>
        )}
      </Sheet>
      <ConfirmSheet open={revoking !== null} onClose={() => setRevoking(null)} title={fill(C.CC_REVOKE_Q, { person: revoking?.person ?? '', book: book.name })}
        body={fill(C.CC_REVOKE_NOTE, { book: book.name })} action={C.CC_REVOKE} variant="primary" busy={busy} error={error} onConfirm={() => void revoke()}
        returnTo={removal.returnTo} />
    </div>
  );
}
