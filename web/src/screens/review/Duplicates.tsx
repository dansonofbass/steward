import { useQueryClient } from '@tanstack/react-query';
import { Trash2 } from 'lucide-react';
import { useState } from 'react';
import { api, del, json } from '../../api/client';
import type { ReviewQueue, Txn } from '../../api/types';
import {
  FROM_A_FILE, FROM_THE_BANK, KEEP_BOTH, POSSIBLE_DUPLICATES, REMOVE, REMOVE_THIS_ONE, REMOVE_THIS_ONE_FOR, REMOVE_TXN_BODY, REMOVE_TXN_BODY_OTHER_FILE, REMOVE_TXN_TITLE,
  TXN_REMOVED,
} from '../../lib/copy';
import { dateLabel } from '../../lib/format';
import { useRemoval } from '../../lib/useRemoval';
import { Button } from '../../ui/Button';
import { ConfirmSheet } from '../../ui/ConfirmSheet';
import { Money } from '../../ui/Money';
import { Notice } from '../../ui/Notice';
import { RemovalLine } from '../../ui/RemovalLine';

function Side({ t, today, onRemove, busy }: { t: Txn; today: Date; onRemove: () => void; busy: boolean }) {
  return (
    <div className="dupe__side">
      <div className="dupe">
        <span className="tag tag--ink">{t.from_bank ? FROM_THE_BANK : FROM_A_FILE}</span>
        <Money cents={t.amount_cents} size="l" />
        <span className="raw">{t.raw_description}</span>
        <span className="small muted">{dateLabel(t.posted_at, today)} · {t.account_name}</span>
      </div>
      {!t.from_bank && (
        <Button variant="danger" icon={Trash2} busy={busy} onClick={onRemove} aria-label={REMOVE_THIS_ONE_FOR.replace('{name}', t.raw_description)}>{REMOVE_THIS_ONE}</Button>
      )}
    </div>
  );
}

export function Duplicates({ pairs, today }: { pairs: ReviewQueue['duplicates']; today: Date }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The file copy a person is about to remove, with its partner: the removal is for good, so it asks first, and what
  // stays is the bank's copy only when the partner came from the bank (a pair can be two file rows).
  const [removing, setRemoving] = useState<{ t: Txn; other: Txn } | null>(null);
  // The section goes with its last pair (Review shows it only while there are some), so the line sits outside it and
  // holds focus after a removal (THO-1).
  const removal = useRemoval();

  async function act(fn: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    removal.clear();
    try {
      await fn();
      await Promise.all(['review', 'transactions', 'spending'].map((k) => qc.invalidateQueries({ queryKey: [k] })));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.');
    } finally {
      setBusy(false);
    }
  }
  async function remove(t: Txn) {
    await act(async () => {
      await api<void>(`/api/transactions/${t.id}`, del());
      removal.removed(TXN_REMOVED.replace('{name}', t.raw_description).replace('{account}', t.account_name));
    });
    setRemoving(null);
  }

  const line = <RemovalLine removal={removal} holdsFocus />;
  if (pairs.length === 0) return line;
  return (
    <>
      {line}
      <section className="stack" aria-labelledby="dup-h">
        <h2 id="dup-h">{POSSIBLE_DUPLICATES}</h2>
        {error && <Notice tone="error">{error}</Notice>}
        {pairs.map(({ a, b }) => (
          <div className="card dupes" key={`${a.id}-${b.id}`}>
            <Side t={a} today={today} busy={busy} onRemove={() => setRemoving({ t: a, other: b })} />
            <div className="dupe__between">
              <Button variant="quiet" busy={busy} onClick={() => { void act(() => api<void>('/api/review/duplicates/keep', json({ a: a.id, b: b.id }))); }}>{KEEP_BOTH}</Button>
            </div>
            <Side t={b} today={today} busy={busy} onRemove={() => setRemoving({ t: b, other: a })} />
          </div>
        ))}
        <ConfirmSheet open={removing !== null} onClose={() => setRemoving(null)} title={REMOVE_TXN_TITLE}
          body={removing?.other.from_bank ? REMOVE_TXN_BODY : REMOVE_TXN_BODY_OTHER_FILE}
          action={REMOVE} icon={Trash2} busy={busy} onConfirm={() => removing && void remove(removing.t)}
          returnTo={removal.returnTo}>
          {removing && <p className="small muted">{removing.t.raw_description} · {dateLabel(removing.t.posted_at, today)} · {removing.t.account_name}</p>}
        </ConfirmSheet>
      </section>
    </>
  );
}
