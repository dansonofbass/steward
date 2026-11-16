import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Undo2 } from 'lucide-react';
import { useState } from 'react';
import { api } from '../../api/client';
import { useCanEdit } from '../../book/BookContext';
import { Link } from '../../book/links';
import { useRemoval } from '../../lib/useRemoval';
import { ALL_TRANSACTIONS, IMPORT_UNDONE, UNDO_IMPORT_BODY, UNDO_IMPORT_ONE_ROW, UNDO_IMPORT_ROWS, UNDO_IMPORT_TITLE, UNDO_THIS_IMPORT } from '../../lib/copy';
import { Button } from '../../ui/Button';
import { ConfirmSheet } from '../../ui/ConfirmSheet';
import { Notice } from '../../ui/Notice';
import { RemovalLine } from '../../ui/RemovalLine';
import { failure } from '../settings/shared';

type One = { id: number; filename: string; rows_in: number; rolled_back_at: string | null; undoable: boolean };
const FROM = 'From {file}';                 // plan-owned
const REFRESH = ['batches', 'accounts', 'summary', 'history', 'transactions', 'review', 'events', 'spending'];

/** "Show all N from this file" (JR, Oct 31): the list filtered to one file, with that file's Undo while it's still in,
 *  reusing today's file Undo and its confirm sheet (plan Engineering choices 4 and 5). Its own lazy chunk. */
export default function BatchBar({ batchId }: { batchId: number }) {
  const qc = useQueryClient();
  const canEdit = useCanEdit();
  const q = useQuery({ queryKey: ['import-batch', batchId], queryFn: () => api<One>(`/api/import/batches/${batchId}`) });
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  // The Undo gives way to the line, which holds focus (THO-1).
  const removal = useRemoval();
  const b = q.data;
  if (!b) return null;
  async function undo() {
    setBusy(true);
    setError('');
    try {
      await api(`/api/import/batches/${batchId}/rollback`, { method: 'POST' });
      removal.removed(IMPORT_UNDONE);
      await Promise.all([...REFRESH, 'import-batch', 'came-from'].map((k) => qc.invalidateQueries({ queryKey: [k] })));
    } catch (e) {
      setError(failure(e));
    }
    setBusy(false);
    setAsking(false);
  }
  const rows = b.rows_in === 1 ? UNDO_IMPORT_ONE_ROW : UNDO_IMPORT_ROWS.replace('{n}', b.rows_in.toLocaleString('en-US'));
  return (
    <div className="batch-bar">
      <span className="batch-bar__name">{FROM.replace('{file}', b.filename)}</span>
      <RemovalLine removal={removal} holdsFocus />
      {!removal.line && canEdit && b.undoable && <Button variant="quiet" icon={Undo2} onClick={() => setAsking(true)}>{UNDO_THIS_IMPORT}</Button>}
      <Link className="link" to="/transactions">{ALL_TRANSACTIONS}</Link>
      {error && <Notice tone="error">{error}</Notice>}
      <ConfirmSheet open={asking} onClose={() => setAsking(false)} title={UNDO_IMPORT_TITLE.replace('{filename}', b.filename)}
        body={UNDO_IMPORT_BODY.replace('{rows}', rows)} action={UNDO_THIS_IMPORT} icon={Undo2} busy={busy} onConfirm={() => void undo()} returnTo={removal.returnTo} />
    </div>
  );
}
