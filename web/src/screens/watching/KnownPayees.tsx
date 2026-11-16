import { useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, Trash2, UserCheck } from 'lucide-react';
import { useState } from 'react';
import { useCanEdit } from '../../book/BookContext';
import { Link } from '../../book/links';
import { TRY_AGAIN } from '../../lib/copy';
import { useRemoval } from '../../lib/useRemoval';
import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import { ConfirmSheet } from '../../ui/ConfirmSheet';
import { Notice } from '../../ui/Notice';
import { RemovalLine } from '../../ui/RemovalLine';
import { Skeleton } from '../../ui/Skeleton';
import { fill } from '../inventory/format';
import { failure } from '../settings/shared';
import { refreshFlags, removeKnown, useWatching, type KnownPayee } from './api';
import * as C from './copy';
import './watching.css';

/** Known payees (README screen 4): every Expected that quiets future flags, and how to undo it (decision 1). */
export function KnownPayees() {
  const q = useWatching();
  const qc = useQueryClient();
  const canEdit = useCanEdit();
  const [removing, setRemoving] = useState<KnownPayee | null>(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // A removed payee says so, and focus goes to the heading rather than the gone row's button (THO-1).
  const removal = useRemoval();
  if (q.isPending) return <Card><Skeleton lines={4} /></Card>;
  if (q.isError) return <Notice tone="error"><p>{q.error.message}</p><Button variant="quiet" onClick={() => q.refetch()}>{TRY_AGAIN}</Button></Notice>;
  const known = q.data.known;

  function ask(k: KnownPayee) {
    setError(null);
    removal.clear();
    setNote('');
    setRemoving(k);
  }

  async function remove() {
    if (!removing) return;
    setBusy(true);
    setError(null);
    try {
      qc.setQueryData(['watching'], await removeKnown(removing.id, note.trim()));
      removal.removed(fill(C.KNOWN_REMOVED, { payee: removing.payee }));
      setRemoving(null);
      setNote('');
      await refreshFlags(qc);
    } catch (e) {
      setError(failure(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="stack" aria-label={C.KNOWN_PAYEES}>
      <Link className="link back" to="/settings/watching"><ChevronLeft className="i" size={20} aria-hidden="true" />{C.WATCHING}</Link>
      <div className="page-head">
        <h2 className="subhead with-icon" ref={removal.anchor} tabIndex={-1}><UserCheck size={20} aria-hidden="true" />{C.KNOWN_PAYEES} <span className="count-pill">{known.length}</span></h2>
        <p className="muted">{C.KNOWN_LEDE}</p>
      </div>
      <RemovalLine removal={removal} />
      {known.length === 0 ? <p className="muted">{C.NO_KNOWN}</p> : (
        <div className="card kp-card">
          <div className="kp-head" aria-hidden="true"><span>{C.KNOWN_HEAD.payee}</span><span>{C.KNOWN_HEAD.amount}</span><span>{C.KNOWN_HEAD.added}</span><span /></div>
          {known.map((k) => (
            <div key={k.id} className="kp">
              <span className="kp__name">{k.payee}</span>
              <span className="kp__sub">{k.range}</span>
              <span className="kp__sub">{k.added}{k.note ? ` · "${k.note}"` : ''}</span>
              {canEdit ? <Button variant="quiet" icon={Trash2} aria-label={fill(C.REMOVE_KNOWN_FOR, { payee: k.payee })} onClick={() => ask(k)}>{C.REMOVE}</Button> : <span />}
            </div>
          ))}
        </div>
      )}
      <p className="small muted">{C.KNOWN_FOOT}</p>
      <ConfirmSheet open={removing !== null} onClose={() => setRemoving(null)} title={removing ? fill(C.REMOVE_KNOWN_TITLE, { payee: removing.payee }) : ''}
        body={removing ? fill(C.REMOVE_KNOWN_BODY, { payee: removing.payee }) : ''} action={C.REMOVE} icon={Trash2} cancel={C.KEEP_IT}
        busy={busy} error={error} onConfirm={() => void remove()} returnTo={removal.returnTo}>
        <div className="field">
          <label className="field__label" htmlFor="known-why">{C.WHY_OPTIONAL}</label>
          <textarea id="known-why" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} />
        </div>
      </ConfirmSheet>
    </section>
  );
}
