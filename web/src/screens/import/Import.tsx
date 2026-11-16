import { useQueryClient } from '@tanstack/react-query';
import { Check, Upload } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ApiError } from '../../api/client';
import { useAccounts } from '../../api/hooks';
import type { Account, AccountType } from '../../api/types';
import { useBook } from '../../book/BookContext';
import { celebrationsChosen, celebrationsOn } from '../../lib/celebrations';
import { collapse } from '../../lib/collapse';
import { BackToSetup } from '../../ui/BackToSetup';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { OopsAcorn } from '../../ui/OopsAcorn';
import { UndoToast } from '../../ui/UndoToast';
import { AddAccountSheet } from '../accounts/ManualAccounts';
import { failure } from '../settings/shared';
import {
  commitBatch, dropFile, previewBatch, REFRESH, rollbackSet, stagedBatch, stageFile, type CommitReply, type PreviewBody,
  type PreviewReply, type StagedFile,
} from './api';
import * as C from './copy';
import { FileRow } from './FileRow';
import { ImportDone } from './ImportDone';
import { Look, type LookLine } from './Look';
import { count, initialAnswers, MAX_BYTES, MAX_FILES, questions, ready, sent, type Answers, type Row } from './logic';
import { Layouts } from './Layouts';
import { PastImports } from './PastImports';
import { Preview } from './Preview';
import { StatementRow } from './StatementRow';
import {
  finalRemove, importable, isPdf, needsLook, oldGatewayNote, MAX_PDF, patchStatement, removeStatement, restoreStatement, statementTag, uploadStatement,
  useStatements, waitingOnIt, type StatementLine,
} from './statements';
import './import.css';

const STORE = 'steward-import:';
type Saved = { batch: string; rows: { token: string; name: string; accountId: number | null; answers: Answers | null; confirmed: boolean }[] };
let seq = 0;
const nextKey = () => `r${(seq += 1)}`;

function fromStaged(f: StagedFile, over: Partial<Row> = {}): Row {
  const held = !!f.held && f.state !== 'new';
  return { key: nextKey(), name: f.name, status: f.error || held ? 'error' : 'ready', file: f, error: f.error ?? (held ? f.held : null),
    accountId: f.account_id, answers: initialAnswers(f), confirmed: false, removed: false, ...over };
}

async function pool<T>(items: T[], n: number, fn: (t: T) => Promise<void>) {
  const queue = [...items];
  await Promise.all(Array.from({ length: Math.min(n, queue.length) }, async () => { while (queue.length) await fn(queue.shift()!); }));
}

const stem = (name: string) => name.replace(/\.[^.]+$/, '').slice(0, 120);
const readSaved = (slug: string): Saved | null => { try { return JSON.parse(sessionStorage.getItem(STORE + slug) ?? 'null'); } catch { return null; } };

/** Settings › Import (import/export spec, Screen: Import): files (drop, read, identify, accounts, questions), then one
 *  preview for the batch, then the result with one Undo. Its own lazy chunk (P35). */
export default function Import() {
  const book = useBook();
  const fromWelcome = useSearchParams()[0].get('from') === 'welcome';
  const slug = book?.slug ?? 'ours';
  const parent = book?.kind === 'parent';
  const qc = useQueryClient();
  const accounts = useAccounts();
  const list = useMemo(() => (accounts.data?.accounts ?? []).filter((a) => a.is_active), [accounts.data]);
  const byId = useMemo(() => new Map(list.map((a) => [a.id, a])), [list]);
  const input = useRef<HTMLInputElement>(null);
  const batchRef = useRef<string | null>(null);
  const listHeading = useRef<HTMLHeadingElement>(null);
  const stepHeading = useRef<HTMLHeadingElement>(null);
  const previewWrap = useRef<HTMLDivElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const [backed, setBacked] = useState(false);
  const [rows, setRows] = useState<Row[]>([]);
  const rowsNow = useRef<Row[]>(rows);
  rowsNow.current = rows;
  const [dragging, setDragging] = useState(false);
  const [announce, setAnnounce] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [step, setStep] = useState<'files' | 'preview'>('files');
  const [preview, setPreview] = useState<PreviewReply | null>(null);
  const [changed, setChanged] = useState(false);
  const [busy, setBusy] = useState<'preview' | 'commit' | null>(null);
  const [include, setInclude] = useState<Record<string, number[]>>({});
  const [simplefinOn, setSimplefinOn] = useState(false);
  const [looking, setLooking] = useState<LookLine | null>(null);
  const [removed, setRemoved] = useState<Row | null>(null);
  const [adding, setAdding] = useState<Row | null>(null);
  const [result, setResult] = useState<CommitReply | null>(null);
  const [undone, setUndone] = useState(false);
  const statements = useStatements();
  const lines = (statements.data?.statements ?? []).filter((s) => !s.removed);
  const gateway = statements.data?.gateway ?? 'answering';
  const [openId, setOpenId] = useState<number | null>(null);
  const [gonePdf, setGonePdf] = useState<StatementLine | null>(null);
  const [pdfErrors, setPdfErrors] = useState<{ key: string; name: string; error: string }[]>([]);
  const [sending, setSending] = useState<{ key: string; name: string }[]>([]);       // PDFs on their way up (P1)
  const tags = useRef<Map<number, string> | null>(null);
  const [pending, setPending] = useState(0);            // requests that change a staged statement, until the refreshed list has landed

  const acct = (r: Row): Account | null => (r.accountId === null ? null : byId.get(r.accountId) ?? null);
  const shown = rows.filter((r) => !r.removed);
  const live = shown.filter((r) => r.status === 'ready');
  const pdfReady = lines.filter(importable);
  const pdfWaiting = sending.length > 0 || lines.some(waitingOnIt);
  const csvReady = live.length > 0 && shown.every((r) => r.status !== 'reading' && ready(r, acct(r)));
  const canPreview = pending === 0 && (csvReady || (live.length === 0 && shown.every((r) => r.status !== 'reading'))) && live.length + pdfReady.length > 0;
  const waitingOn = shown.find((r) => r.status === 'ready' && questions(r, acct(r)) > 0);

  useEffect(() => {                                   // the polite line: the newest change, never on the first load
    const d = statements.data;
    if (!d) return;
    const next = new Map<number, string>();
    let changed: string | null = null;
    for (const s of d.statements.filter((x) => !x.removed)) {
      const t = statementTag(s, d.gateway);
      next.set(s.id, t);
      const was = tags.current?.get(s.id);
      if (was !== undefined && was !== t) changed = C.ST_ANNOUNCE.replace('{file}', s.name).replace('{tag}', t);
    }
    tags.current = next;
    if (changed) setAnnounce(changed);
  }, [statements.data]);

  useEffect(() => {                                   // P6: come back to the batch within 30 minutes
    const saved = readSaved(slug);
    if (!saved) return;
    stagedBatch(saved.batch).then((res) => {
      batchRef.current = res.batch;
      setRows(res.files.map((f) => {
        const s = saved.rows.find((x) => x.token === f.token);
        return fromStaged(f, s ? { accountId: s.accountId, answers: s.answers ?? initialAnswers(f), confirmed: s.confirmed } : {});
      }));
    }).catch(() => {
      setRows(saved.rows.map((s) => ({ key: nextKey(), name: s.name, status: 'expired', file: null, error: null, accountId: null,
        answers: null, confirmed: false, removed: false })));
      setNotice(C.EXPIRED);
      try { sessionStorage.removeItem(STORE + slug); } catch { /* private mode */ }
    });
  }, [slug]);

  useEffect(() => {                                   // only the batch id, tokens, names and choices; never a cell
    try {
      const keep = rows.filter((r) => r.file?.token && !r.removed && r.status === 'ready');
      if (!batchRef.current || keep.length === 0) sessionStorage.removeItem(STORE + slug);
      else sessionStorage.setItem(STORE + slug, JSON.stringify({ batch: batchRef.current, rows: keep.map((r) => ({
        token: r.file!.token, name: r.name, accountId: r.accountId, answers: r.answers, confirmed: r.confirmed })) }));
    } catch { /* private mode */ }
  }, [rows, slug]);

  useEffect(() => { if (step === 'preview') stepHeading.current?.focus(); }, [step]);
  useEffect(() => { if (result) resultRef.current?.focus(); }, [result]);
  useEffect(() => {                                   // after Back: the first file that needs something, else Preview
    if (step !== 'files' || !backed) return;
    setBacked(false);
    const first = rows.find((r) => !r.removed && r.status === 'ready' && !ready(r, acct(r)));
    const sel = first && document.querySelector<HTMLElement>(`[aria-label="${C.ACCOUNT_FOR.replace('{file}', first.name)}"]`);
    (sel ?? previewWrap.current?.querySelector('button'))?.focus();
  });

  // Spec, Accessibility: a line that is done closes and focus moves on. After Looks right, to the next line needing a
  // look, else Preview; after Done, to the line itself. It waits until the refreshed list shows the state the line reached.
  const afterLook = useRef<{ id: number; to: StatementLine['state']; next: boolean } | null>(null);
  useEffect(() => {
    const p = afterLook.current;
    if (!p || openId === p.id) return;
    if (openId !== null) { afterLook.current = null; return; }         // the person has moved on to another line
    if (lines.find((s) => s.id === p.id)?.state !== p.to) return;
    afterLook.current = null;
    const at = lines.findIndex((s) => s.id === p.id);
    const others = [...lines.slice(at + 1), ...lines.slice(0, at), lines[at]].filter((s) => needsLook(s));
    const own = document.querySelector<HTMLElement>(`[data-look="${p.id}"]`) ?? document.querySelector<HTMLElement>(`[data-account="${p.id}"]`);
    const next = p.next ? others.map((s) => document.querySelector<HTMLElement>(`[data-look="${s.id}"]`)).find(Boolean) : own;
    (next ?? (p.next ? previewWrap.current?.querySelector('button') : own))?.focus();
  });
  function lookDone(id: number, to: StatementLine['state'], next: boolean) {
    afterLook.current = { id, to, next };
    setOpenId((cur) => (cur === id ? null : cur));      // the reply is async: another line opened meanwhile stays open
  }

  function expire() {
    batchRef.current = null;
    setRows((rs) => rs.map((r) => (r.removed ? r : { ...r, status: 'expired' })));
    setStep('files');
    setPreview(null);
    setNotice(C.EXPIRED);
  }

  async function upload(r: Row) {
    try {
      const res = await stageFile(r.blob!, batchRef.current);
      batchRef.current = res.batch;
      setRows((rs) => rs.flatMap((x) => (x.key === r.key ? res.files.map((f, i) => fromStaged(f, i === 0 ? { key: r.key, removed: x.removed } : {})) : [x])));
    } catch (e) {
      if (e instanceof ApiError && e.status === 410) expire();
      else setRows((rs) => rs.map((x) => (x.key === r.key ? { ...x, status: 'error', error: failure(e) } : x)));
    }
  }

  const refreshLines = () => qc.invalidateQueries({ queryKey: ['statements'] });

  async function sendPdf(f: File, key: string) {
    try {
      await uploadStatement(f, batchRef.current);
    } catch (e) {
      setPdfErrors((x) => [...x, { key: nextKey(), name: f.name, error: failure(e) }]);
    }
    await refreshLines();
    setSending((x) => x.filter((y) => y.key !== key));
  }

  async function addFiles(files: File[]) {
    setResult(null);
    setUndone(false);
    setNotice(null);
    const room = Math.max(0, MAX_FILES - rows.filter((r) => !r.removed && (r.status === 'ready' || r.status === 'reading')).length
      - lines.filter((s) => s.state !== 'cleared').length - sending.length);
    if (files.length > room) setNotice(C.TOO_MANY);
    const taken = files.slice(0, room);
    const pdfs = taken.filter(isPdf);
    const others = taken.filter((f) => !isPdf(f));
    const fresh: Row[] = others.map((f) => ({ key: nextKey(), name: f.name, status: f.size > MAX_BYTES ? 'error' : 'reading',
      file: null, error: f.size > MAX_BYTES ? C.TOO_BIG : null, accountId: null, answers: null, confirmed: false, removed: false, blob: f }));
    const okPdfs = pdfs.filter((f) => f.size <= MAX_PDF);
    const bigPdfs = pdfs.filter((f) => f.size > MAX_PDF);
    if (bigPdfs.length) setPdfErrors((x) => [...x, ...bigPdfs.map((f) => ({ key: nextKey(), name: f.name, error: C.TOO_BIG_PDF }))]);
    const toSend = okPdfs.map((f) => ({ f, key: nextKey() }));
    setRows((rs) => [...rs, ...fresh]);
    setSending((x) => [...x, ...toSend.map(({ f, key }) => ({ key, name: f.name }))]);
    const queue = fresh.filter((r) => r.status === 'reading');
    if (queue.length === 0 && toSend.length === 0) return;
    const n = queue.length + toSend.length;
    setAnnounce(n === 1 ? C.READING_ONE : C.READING_N.replace('{n}', String(n)));
    if (!batchRef.current && queue.length) await upload(queue.shift()!);      // the first CSV sets the batch the PDFs count against
    await Promise.all([pool(queue, 3, upload), pool(toSend, 2, ({ f, key }) => sendPdf(f, key))]);
    setAnnounce(n === 1 ? C.READ_ONE : C.READ_N.replace('{n}', String(n)));
  }

  const patch = (key: string, p: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...p } : r)));

  function choose(r: Row, value: string) {
    if (value === 'new') { setAdding(r); return; }
    patch(r.key, { accountId: value ? Number(value) : null });
  }

  // A change to a staged statement bumps its version, which the preview's digest covers: Preview waits until it has settled.
  async function track<T>(p: Promise<T>): Promise<T> {
    setPending((n) => n + 1);
    try {
      const r = await p;
      await refreshLines();
      return r;
    } finally {
      setPending((n) => n - 1);
    }
  }

  function choosePdf(line: StatementLine, value: string) {
    track(patchStatement(line.id, { account_id: value ? Number(value) : null })).catch((e) => setError(failure(e)));
  }

  function finishPdfRemoval() {
    const g = gonePdf;
    setGonePdf(null);
    if (g) finalRemove(g.id).catch((e) => setError(failure(e)));
  }

  function removePdf(line: StatementLine, el: HTMLElement | null) {
    if (gonePdf) finishPdfRemoval();
    collapse(el, () => {
      removeStatement(line.id).then(refreshLines).catch((e) => setError(failure(e)));
      setGonePdf(line);
      listHeading.current?.focus();
    });
  }

  function undoPdf() {
    const g = gonePdf;
    setGonePdf(null);
    if (g) restoreStatement(g.id).then(refreshLines).catch((e) => setError(failure(e)));
  }

  function finishRemoval() {
    const r = removed;
    setRemoved(null);
    if (!r) return;
    const now = rowsNow.current.find((x) => x.key === r.key) ?? r;      // it may have finished reading since the click
    setRows((rs) => rs.filter((x) => x.key !== r.key));
    if (now.file?.token && now.status === 'ready') void dropFile(now.file.token).catch(() => undefined);
  }

  function remove(r: Row, el: HTMLElement | null) {
    if (removed) finishRemoval();
    collapse(el, () => { patch(r.key, { removed: true }); setRemoved(r); listHeading.current?.focus(); });
  }

  function body(inc = include, sfOn = simplefinOn, reply = preview): PreviewBody {
    return { batch: live.length ? batchRef.current : null, files: live.map((r) => ({ token: r.file!.token!, account_id: r.accountId!,
      layout: sent(r, acct(r)), include: inc[r.file!.token!] ?? [] })),
    statements: pdfReady.map((s) => ({ id: s.id, account_id: s.account_id!, include: inc[`s${s.id}`] ?? [] })),
    simplefin_include: sfOn ? (reply?.look.simplefin.map((g) => g.account_id) ?? []) : [] };
  }

  async function runPreview(inc = include, sfOn = simplefinOn) {
    setBusy('preview');
    setError('');
    try {
      const p = await previewBatch(body(inc, sfOn));
      setPreview(p);
      setChanged(false);
      setStep('preview');
    } catch (e) {
      if (e instanceof ApiError && e.status === 410) expire();
      else setError(failure(e));
    }
    setBusy(null);
  }

  function back() {
    setStep('files');
    setChanged(false);
    setBacked(true);
  }

  async function doImport() {
    if (!preview) return;
    setBusy('commit');
    setError('');
    try {
      const r = await commitBatch({ ...body(), digest: preview.digest });
      if (gonePdf) finishPdfRemoval();                  // one toast: the import's Undo, never under a Removed one
      if (removed) finishRemoval();
      setResult(r);
      setRows([]);
      batchRef.current = null;
      setStep('files');
      setPreview(null);
      setInclude({});
      setSimplefinOn(false);
      setPdfErrors([]);
      await Promise.all([...REFRESH, 'statements'].map((k) => qc.invalidateQueries({ queryKey: [k] })));
    } catch (e) {
      const fresh = (e as ApiError).body as { preview?: PreviewReply } | null;
      if (e instanceof ApiError && e.status === 409 && fresh?.preview) { setPreview(fresh.preview); setChanged(true); }
      else if (e instanceof ApiError && e.status === 410) expire();
      else setError(failure(e));
    }
    setBusy(null);
  }

  async function undoResult() {
    if (!result) return;
    const id = result.set_id;
    setResult(null);
    try {
      await rollbackSet(id);
      setUndone(true);
      await Promise.all(REFRESH.map((k) => qc.invalidateQueries({ queryKey: [k] })));
    } catch (e) {
      setError(failure(e));
    }
  }

  const resultText = result && (result.accounts === 1 && result.account
    ? C.RESULT_ONE.replace('{n}', count(result.imported)).replace('{account}', result.account)
    : C.RESULT_N.replace('{n}', count(result.imported)).replace('{k}', String(result.accounts)));

  return (
    <section className="spage imp" aria-labelledby="import-h">
      {fromWelcome && <BackToSetup step="money" />}
      <h2 id="import-h">{C.HEADING}</h2>
      {step === 'files' && (
        <>
          <section className={`imp-drop${dragging ? ' is-dragging' : ''}`} aria-labelledby="imp-drop-h"
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); void addFiles(Array.from(e.dataTransfer.files)); }}>
            <p id="imp-drop-h" className="imp-drop__title">{C.DROP}</p>
            <Button icon={Upload} onClick={() => input.current?.click()}>{C.CHOOSE}</Button>
            <input ref={input} type="file" multiple accept=".csv,.ofx,.qfx,.pdf" hidden
              onChange={(e) => { void addFiles(Array.from(e.target.files ?? [])); e.target.value = ''; }} />
            <p className="small muted">{C.FORMATS}</p>
          </section>
          <p role="status" className="sr-only">{announce}</p>
          {notice && <Notice tone="warn">{notice}</Notice>}
          {shown.length + lines.length + sending.length + pdfErrors.length > 0 && (
            <>
              <h3 className="sr-only" tabIndex={-1} ref={listHeading}>{C.HEADING}</h3>
              <ul className="plain imp-rows">
                {shown.map((r) => (
                  <FileRow key={r.key} row={r} account={acct(r)} accounts={list} parent={parent}
                    onAccount={(v) => choose(r, v)} onAnswers={(answers) => patch(r.key, { answers })}
                    onUse={(el) => collapse(el, () => { patch(r.key, { confirmed: true }); listHeading.current?.focus(); })}
                    onRemove={(el) => remove(r, el)} />
                ))}
                {lines.map((s) => (
                  <StatementRow key={`s-${s.id}`} line={s} gateway={gateway} accounts={list} open={openId === s.id}
                    onOpen={() => setOpenId(openId === s.id ? null : s.id)}
                    onDone={(to) => lookDone(s.id, to, s.state === 'layout')} onAccount={(v) => choosePdf(s, v)} track={track}
                    onRemove={(el) => removePdf(s, el)} />
                ))}
                {sending.map((x) => (
                  <li key={x.key} className="imp-row" aria-busy="true">
                    <div className="imp-row__line"><span className="imp-row__name">{x.name}</span><span className="imp-row__tag">{C.READING}</span></div>
                  </li>
                ))}
                {pdfErrors.map((e) => (
                  <li key={e.key} className="imp-row">
                    <div className="imp-row__line"><span className="imp-row__name">{e.name}</span><OopsAcorn /><span className="imp-row__tag imp-row__tag--warn">{e.error}</span></div>
                  </li>
                ))}
              </ul>
              {gateway === 'old' && lines.some((s) => s.state === 'waiting') && <p className="small muted">{oldGatewayNote(statements.data?.reading)}</p>}
              <div className="row-actions" ref={previewWrap}>
                {waitingOn && <p id="imp-why" className="sr-only">{C.ANSWER_FOR.replace('{file}', waitingOn.name)}</p>}
                <Button busy={busy === 'preview'} disabled={!canPreview} aria-describedby={waitingOn ? 'imp-why' : undefined}
                  onClick={() => void runPreview()}>{pdfWaiting ? C.PREVIEW_SOME.replace('{n}', String(live.length + pdfReady.length)) : C.PREVIEW}</Button>
              </div>
            </>
          )}
        </>
      )}
      {step === 'preview' && preview && (
        <Preview reply={preview} changed={changed} busy={busy === 'commit'} headingRef={stepHeading} onImport={() => void doImport()}
          onBack={back} onLook={setLooking} />
      )}
      {error && <Notice tone="error">{error}</Notice>}
      <div ref={resultRef} tabIndex={-1} className="imp-result">
        {result && resultText && (
          <>
            <UndoToast key={result.set_id} text={resultText} onUndo={() => void undoResult()} onClose={() => setResult(null)} />
            {result.imported > 0 && typeof result.waiting === 'number' && <ImportDone key={`done-${result.set_id}`} n={result.imported} m={result.waiting} />}
            {result.statements >= 2 && result.added_up === result.statements && celebrationsChosen()
              ? <p className={`imp-joy${celebrationsOn() ? ' imp-joy--lively' : ''}`}><Check className="imp-joy__mark" aria-hidden="true" />{C.ST_JOY.replace('{n}', String(result.statements))}</p>
              : result.months >= 12 && <p className={`imp-joy${celebrationsOn() ? ' imp-joy--lively' : ''}`}>{C.JOY.replace('{n}', String(result.months))}</p>}
          </>
        )}
        {undone && <UndoToast key="undone" text={C.UNDONE} onClose={() => setUndone(false)} />}
      </div>
      {removed && <UndoToast key={`rm-${removed.key}`} text={C.REMOVED.replace('{file}', removed.name)}
        onUndo={() => { patch(removed.key, { removed: false }); setRemoved(null); }} onClose={finishRemoval} />}
      {gonePdf && <UndoToast key={`pdf-${gonePdf.id}`} text={C.REMOVED.replace('{file}', gonePdf.name)} onUndo={undoPdf} onClose={finishPdfRemoval} />}
      {looking && preview && (
        <Look line={looking} reply={preview} include={include} simplefinOn={simplefinOn} onClose={() => setLooking(null)}
          onDone={(inc, on) => { setLooking(null); setInclude(inc); setSimplefinOn(on); void runPreview(inc, on); }} />
      )}
      {adding && (
        <AddAccountSheet initialName={stem(adding.name)} initialType={(adding.file?.card ? 'credit' : 'checking') as AccountType}
          onClose={() => setAdding(null)} onSaved={(id) => { if (id) patch(adding.key, { accountId: id }); setAdding(null); }} />
      )}
      <PastImports />
      <Layouts />
    </section>
  );
}
