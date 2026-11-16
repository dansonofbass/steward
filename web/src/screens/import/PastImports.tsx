import { useQueryClient } from '@tanstack/react-query';
import { File as FileIcon, Undo2 } from 'lucide-react';
import { useState } from 'react';
import { dateLabelFromIso, localYmd } from '../../lib/format';
import { useRemoval } from '../../lib/useRemoval';
import { IMPORT_UNDONE, PAST_IMPORTS, UNDO_IMPORT_BODY, UNDO_IMPORT_ONE_ROW, UNDO_IMPORT_ROWS, UNDO_IMPORT_TITLE, UNDO_THIS_IMPORT } from '../../lib/copy';
import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import { ConfirmSheet } from '../../ui/ConfirmSheet';
import { Notice } from '../../ui/Notice';
import { RemovalLine } from '../../ui/RemovalLine';
import { Skeleton } from '../../ui/Skeleton';
import { failure } from '../settings/shared';
import { REFRESH, rollbackFile, rollbackSet, useImports, type BatchFile, type ImportGroup } from './api';
import * as C from './copy';
import { count, monthDay } from './logic';
import { monthYear } from './statements';

type Asking = { kind: 'set'; group: ImportGroup } | { kind: 'file'; file: BatchFile };
const rowsOf = (g: ImportGroup) => g.files.reduce((n, f) => n + f.row_count, 0);

/** P20: Past imports grouped by batch. A batch expands to its files; Undo this import keeps today's confirm sheet;
 *  each file keeps its own Undo; a file from before batches is a batch of one. */
export function PastImports() {
  const imports = useImports();
  const qc = useQueryClient();
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [asking, setAsking] = useState<Asking | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  // An undone import says so, and focus goes to the heading: the Undo that opened the sheet gives way to "Undone" (THO-1).
  const removal = useRemoval();
  const today = new Date();

  async function undo(a: Asking) {
    setBusy(true);
    setError('');
    removal.clear();
    try {
      await (a.kind === 'set' ? rollbackSet(a.group.set_id!) : rollbackFile(a.file.id));
      await Promise.all(REFRESH.map((k) => qc.invalidateQueries({ queryKey: [k] })));
      removal.removed(IMPORT_UNDONE);
    } catch (e) {
      setError(failure(e));
    }
    setBusy(false);
    setAsking(null);
  }

  const fileLine = (f: BatchFile) => (
    <li className={`line batch${f.rolled_back_at ? ' is-undone' : ''}`} key={f.id}>
      <div className="line__lead">
        <FileIcon size={20} aria-hidden="true" />
        <div className="line__main">
          {f.format === 'pdf' || f.format === 'pdf_scan'
            ? (
              <>
                <span>{C.PAST_PDF.replace('{account}', f.account_name ?? C.REMOVED_ACCOUNT).replace('{month}', f.period_end ? monthYear(f.period_end) : f.filename)
                  .replace('{rows}', count(f.row_count))}</span>
                <span className="small muted">{dateLabelFromIso(f.imported_at, today)}
                  {f.check_state === 'anyway' && <> · <span className="imp-row__tag--warn">{C.PAST_OFF}</span></>}</span>
              </>
            )
            : (
              <>
                <span>{f.filename}</span>
                <span className="small muted">{f.account_name ?? C.REMOVED_ACCOUNT} · {count(f.row_count)} rows · {dateLabelFromIso(f.imported_at, today)}</span>
              </>
            )}
        </div>
      </div>
      {f.rolled_back_at
        ? <span className="small muted">{C.UNDONE_ON.replace('{date}', dateLabelFromIso(f.rolled_back_at, today))}</span>
        : <Button variant="quiet" icon={Undo2} onClick={() => setAsking({ kind: 'file', file: f })}>{UNDO_THIS_IMPORT}</Button>}
    </li>
  );

  const sheet = asking && (asking.kind === 'set'
    ? { title: C.UNDO_SET_TITLE.replace('{n}', String(asking.group.files.length)),
        body: C.UNDO_SET_BODY.replace('{rows}', count(rowsOf(asking.group))).replace('{n}', String(asking.group.files.length)) }
    : { title: UNDO_IMPORT_TITLE.replace('{filename}', asking.file.filename),
        body: UNDO_IMPORT_BODY.replace('{rows}', asking.file.row_count === 1 ? UNDO_IMPORT_ONE_ROW : UNDO_IMPORT_ROWS.replace('{n}', count(asking.file.row_count))) });

  return (
    <section className="step" aria-labelledby="past-h">
      <h3 id="past-h" className="subhead" ref={removal.anchor} tabIndex={-1}>{PAST_IMPORTS}</h3>
      <RemovalLine removal={removal} />
      {error && <Notice tone="error">{error}</Notice>}
      {imports.isPending && <Card><Skeleton lines={2} /></Card>}
      {imports.isError && <Notice tone="error">{imports.error.message}</Notice>}
      {imports.isSuccess && imports.data.imports.length === 0 && <p className="muted">{C.NOTHING_YET}</p>}
      {imports.isSuccess && imports.data.imports.length > 0 && (
        <Card className="lines">
          <ul className="plain">
            {imports.data.imports.map((g) => (g.set_id === null || g.files.length === 1 ? fileLine(g.files[0]) : (
              <li key={`s${g.set_id}`} className={`imp-set${g.rolled_back_at ? ' is-undone' : ''}`}>
                <div className="line">
                  <button type="button" className="link imp-set__toggle" aria-expanded={open.has(g.set_id)}
                    onClick={() => setOpen((s) => { const n = new Set(s); if (n.has(g.set_id!)) n.delete(g.set_id!); else n.add(g.set_id!); return n; })}>
                    {C.PAST_BATCH.replace('{n}', String(g.files.length)).replace('{rows}', count(rowsOf(g))).replace('{date}', monthDay(localYmd(g.imported_at)))}
                  </button>
                  {g.rolled_back_at
                    ? <span className="small muted">{C.UNDONE_ON.replace('{date}', dateLabelFromIso(g.rolled_back_at, today))}</span>
                    : <Button variant="quiet" icon={Undo2} onClick={() => setAsking({ kind: 'set', group: g })}>{UNDO_THIS_IMPORT}</Button>}
                </div>
                {open.has(g.set_id) && <ul className="plain imp-set__files">{g.files.map(fileLine)}</ul>}
              </li>
            )))}
          </ul>
        </Card>
      )}
      <ConfirmSheet open={asking !== null} onClose={() => setAsking(null)} title={sheet?.title ?? ''} body={sheet?.body}
        action={UNDO_THIS_IMPORT} icon={Undo2} busy={busy} onConfirm={() => asking && void undo(asking)} returnTo={removal.returnTo} />
    </section>
  );
}
