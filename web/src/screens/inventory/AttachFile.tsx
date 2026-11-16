import { useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, CircleCheck, CircleX, FileText, FileUp, Receipt, Upload, X } from 'lucide-react';
import { useRef, useState, type DragEvent } from 'react';
import { useParams } from 'react-router-dom';
import { isAbort } from '../../api/client';
import { useBook, useCanEdit } from '../../book/BookContext';
import { Link, Navigate, useNavigate } from '../../book/links';
import { TRY_AGAIN } from '../../lib/copy';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { failure } from '../settings/shared';
import { refreshInventory, uploadFile, useItem } from './api';
import * as C from './copy';
import { fill, longLabel, parentName } from './format';
import './inventory.css';

type Row = { key: number; name: string; state: 'uploading' | 'done' | 'refused'; sent: number; total: number; detail: string;
  fileId?: number; taxForm?: boolean; stop?: () => void };
const size = (n: number) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);

export function AttachFile() {
  const { id = '' } = useParams();
  const itemId = Number(id);
  const book = useBook();
  const canEdit = useCanEdit();
  const q = useItem(itemId, canEdit);
  const [rows, setRows] = useState<Row[]>([]);
  const [confirm, setConfirm] = useState(true);
  const input = useRef<HTMLInputElement>(null);
  const next = useRef(0);
  const qc = useQueryClient();
  const navigate = useNavigate();

  if (!canEdit) return <Navigate to={`/inventory/${id}`} replace />;   // ruling 8
  if (q.isPending) return <div className="screen" aria-busy="true"><Skeleton lines={4} /></div>;
  if (q.isError) return <div className="screen"><Notice tone="error"><p>{q.error.message}</p><Button variant="quiet" onClick={() => q.refetch()}>{TRY_AGAIN}</Button></Notice></div>;
  const it = q.data;
  if (it.status === 'closed') return <Navigate to={`/inventory/${id}`} replace />;   // a closed item takes no files, as its page shows
  const needs = it.status === 'needs_checking';
  const update = (key: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  function start(files: FileList | File[]) {
    for (const file of Array.from(files)) {
      const key = next.current++;
      const ctl = new AbortController();
      setRows((rs) => [...rs, { key, name: file.name, state: 'uploading', sent: 0, total: file.size, detail: '', stop: () => ctl.abort() }]);
      uploadFile(file, { itemId, confirm: needs && confirm }, (sent, total) => update(key, { sent, total }), ctl.signal)
        .then(async (r) => {
          update(key, { state: 'done', detail: fill(C.ATTACHED_LINE, { label: r.file.label, size: r.file.size_label }), fileId: r.file.id, taxForm: r.looks_like_tax_form });
          await refreshInventory(qc);
        })
        .catch((e) => {
          if (isAbort(e)) setRows((rs) => rs.filter((r) => r.key !== key));
          else update(key, { state: 'refused', detail: failure(e) });
        });
    }
  }
  const onDrop = (e: DragEvent) => { e.preventDefault(); start(e.dataTransfer.files); };
  const label = longLabel(it.name, it.institution, it.last4, it.kind);

  return (
    <div className="screen attach">
      <header className="page-head">
        <Link className="link back" to={`/inventory/${it.id}`}><ChevronLeft className="i" size={20} aria-hidden="true" />{it.name}</Link>
        <h1>{C.ATTACH_A_FILE}</h1>
        <p className="muted">{fill(needs ? C.ATTACH_TO_CHECKING : C.ATTACH_TO, { label })}</p>
      </header>
      <section className="stack" aria-label={C.ATTACH_A_FILE}>
        <div className="drop" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
          <FileUp size={20} aria-hidden="true" />
          <p className="strong">{C.DROP}</p>
          <Button icon={Upload} onClick={() => input.current?.click()}>{C.CHOOSE_FILE}</Button>
          <input ref={input} type="file" multiple hidden aria-label={C.CHOOSE_FILE} accept=".pdf,.png,.jpg,.jpeg,.heic,.csv"
            onChange={(e) => { if (e.target.files) start(e.target.files); e.target.value = ''; }} />
          <p className="small muted">{C.ALLOWED}</p>
        </div>
        {rows.length > 0 && (
          <div className="card files">
            {rows.map((r) => (
              <div key={r.key}>
                <div className="file">
                  {r.state === 'done' ? <CircleCheck size={20} aria-hidden="true" className="money--in" /> : r.state === 'refused' ? <CircleX size={20} aria-hidden="true" className="danger" /> : <FileText size={20} aria-hidden="true" />}
                  <div className="file__main">
                    <span className="file__name">{r.name}</span>
                    {r.state === 'uploading' && <div className="inv-progress"><span style={{ width: `${r.total ? Math.round((100 * r.sent) / r.total) : 0}%` }} /></div>}
                    <span className={`file__sub${r.state === 'refused' ? ' danger' : ''}`}>{r.state === 'uploading' ? fill(C.UPLOADING, { sent: size(r.sent), total: size(r.total) }) : r.detail}</span>
                  </div>
                  {r.state === 'uploading' && <button className="btn btn--quiet" type="button" onClick={r.stop}><span className="btn__content"><X size={20} aria-hidden="true" /><span>{C.STOP}</span></span></button>}
                </div>
                {r.taxForm && r.fileId !== undefined && (
                  <div className="file file--nudge">
                    <Receipt size={20} aria-hidden="true" />
                    <div className="file__main"><span className="file__name">{C.LOOKS_LIKE_TAX}</span><span className="file__sub">{fill(C.LOOKS_LIKE_TAX_BODY, { name: parentName(book) })}</span></div>
                    <Link className="btn btn--quiet" to={`/inventory/tax-form?file=${r.fileId}&name=${encodeURIComponent(r.name)}`}><span className="btn__content"><span>{C.TYPE_IT_IN}</span></span></Link>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        {needs && (
          <label className="radio-row">
            <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
            <span>{fill(C.MARK_ITEM_CONFIRMED, { name: it.name })}<small className="small muted">{fill(C.MARK_HINT, { institution: it.institution ?? it.name })}</small></span>
          </label>
        )}
        <div className="row-actions"><Button onClick={() => navigate(`/inventory/${it.id}`)}>{C.DONE}</Button></div>
      </section>
    </div>
  );
}

export default AttachFile;
