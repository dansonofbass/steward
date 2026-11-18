import { useQueryClient } from '@tanstack/react-query';
import { Check, ChevronLeft, ChevronRight, CircleCheck, Flag, History, Hourglass, RotateCcw, Undo2 } from 'lucide-react';
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { aboutFor } from '../../ask/about';
import { useCanEdit } from '../../book/BookContext';
import { Link } from '../../book/links';
import { money } from '../../lib/format';
import { ALL_TRANSACTIONS, FLAG_THING, TRY_AGAIN } from '../../lib/copy';
import { AskAbout } from '../../ui/AskAbout';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import '../inventory/inventory.css';
import { fill } from '../inventory/format';
import { failure } from '../settings/shared';
import { reopenFlag, refreshFlags, useFlag, type FlagPage as Page, type MiniTxn } from './api';
import * as C from './copy';
import { CheckMark, FlagStatusMark, UrgentMark, WATCH_ICONS } from './marks';
import { MarkSheet, type Mode } from './MarkSheet';
import './watching.css';

const stamp = (iso: string) => new Date(iso).toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });

function Minis({ rows }: { rows: MiniTxn[] }) {
  return (
    <div className="mini-txns">
      {rows.map((r) => (
        <div key={r.meta + r.amount_cents} className="txn">
          <span className="txn__name">{r.name}</span><span className="money money--m">{money(r.amount_cents)}</span>
          <span className="txn__meta">{r.meta}{r.raw && <> · <span className="raw">{r.raw}</span></>}</span>
        </div>
      ))}
    </div>
  );
}

// Keyed by id so a sheet, a done line or an error never carries over to the next flag.
export function FlagPage() {
  const { id = '' } = useParams();
  return <FlagBody key={id} flagId={Number(id)} />;
}

function FlagBody({ flagId }: { flagId: number }) {
  const q = useFlag(flagId);
  // The tab keeps the fixed noun: a flag's title describes a money worry, and a page title goes into the browser's
  // history (issue #29, privacy ruling; routeTitles.test.tsx).
  const qc = useQueryClient();
  const canEdit = useCanEdit();
  const [mode, setMode] = useState<Mode | null>(null);
  const [doneLine, setDoneLine] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (q.isPending) return <div className="screen" aria-busy="true"><Skeleton lines={8} /></div>;
  if (q.isError) return <div className="screen"><Notice tone="error"><p>{q.error.message}</p><Button variant="quiet" onClick={() => q.refetch()}>{TRY_AGAIN}</Button></Notice></div>;
  const f = q.data;

  async function done(page: Page) {
    qc.setQueryData(['flags', 'one', flagId], page);
    setDoneLine(page.done_line ?? null);
    setMode(null);
    await refreshFlags(qc);
  }
  async function reopen() {
    setBusy(true);
    setError(null);
    try {
      await done(await reopenFlag(f.id));
    } catch (e) {
      setError(failure(e));
    } finally {
      setBusy(false);
    }
  }
  const t = f.transaction;
  return (
    <div className="screen flag-page">
      <header className="flag-head">
        <Link className="link back" to="/look-into"><ChevronLeft className="i" size={20} aria-hidden="true" />{C.LOOK_INTO}</Link>
        <p className="eyebrow">{C.FLAG}</p>
        <h1>{f.title}</h1>
        <p className="row-actions">
          {f.urgent && <UrgentMark />}<CheckMark check={f.check} label={f.check_label} />
          <FlagStatusMark status={f.status} label={f.status_label} by={f.status === 'open' ? null : f.by} />
          <AskAbout about={aboutFor.flag(f)} surface={{ kind: 'flag' }} thing={FLAG_THING.replace('{check}', f.check_label)} />
          <span className="small muted">{fill(C.FLAGGED_AT, { when: stamp(f.flagged_at) })}</span>
        </p>
      </header>

      {error && <Notice tone="error">{error}</Notice>}
      {doneLine && (
        <div className="card done-line">
          <CircleCheck size={20} aria-hidden="true" /><span className="grow">{doneLine}</span>
          {canEdit && f.status === 'expected' && <Button variant="quiet" icon={Undo2} busy={busy} onClick={() => void reopen()}>{C.UNDO}</Button>}
        </div>
      )}
      {f.status === 'checking' && f.note && (
        <Notice tone="warn">
          <span className="stack stack--tight">
            <span><Hourglass size={20} aria-hidden="true" /> <strong>{fill(C.IS_CHECKING, { who: f.note_by ?? '' })}</strong> <span>"{f.note}"</span></span>
            <span className="small muted">{f.status_at ? stamp(f.status_at) : ''}{canEdit && <> · <button className="link-btn" type="button" onClick={() => setMode('note')}>{C.CHANGE_NOTE}</button></>}</span>
          </span>
        </Notice>
      )}

      <div className="item">
        <div className="item__col">
          <section className="stack stack--tight" aria-label={C.WHY_FLAGGED}>
            <h2 className="subhead">{C.WHY_FLAGGED}</h2>
            <div className="card flag-facts">
              <p><b>{f.check_label}:</b> {f.fact}</p>
              <p className="small muted">{f.why}</p>
              {f.also.length > 0 && (
                <p className="small"><span className="muted">{C.ALSO_MATCHED}</span>{f.also.map((a) => (
                  <span key={a.check}> <CheckMark check={a.check} label={a.label} /> <span className="muted">({a.detail})</span></span>
                ))}</p>
              )}
            </div>
          </section>

          {f.payments.length > 0 && (
            <section className="stack stack--tight" aria-label={C.RECENT_PAYMENTS}>
              <h2 className="subhead">{C.RECENT_PAYMENTS}</h2>
              <div className="card stack"><Minis rows={f.payments} />
                {f.related_line && <p className="small muted">{f.related_line}</p>}
                {f.expected_note && <p className="small muted">{f.expected_note}</p>}
              </div>
            </section>
          )}

          {t && (
            <section className="stack stack--tight" aria-label={C.THE_TRANSACTION}>
              <div className="sec-h"><h2 className="subhead">{C.THE_TRANSACTION}</h2><Link className="link" to="/transactions">{ALL_TRANSACTIONS}<ChevronRight size={20} aria-hidden="true" /></Link></div>
              {t.removed && <Notice>{C.REMOVED}</Notice>}
              <div className="card txcard">
                <div className="txcard__top"><span className="strong">{t.payee}</span>{t.amount_cents !== null && <span className="money money--xl">{money(t.amount_cents)}</span>}</div>
                <dl className="ifacts">
                  <dt>{C.F.date}</dt><dd>{t.date_label}</dd>
                  <dt>{C.F.paidFrom}</dt><dd>{t.account}{t.joint_names && <span className="small muted"> ({t.joint_names})</span>}</dd>
                  <dt>{C.F.banksText}</dt><dd><span className="raw">{t.raw}</span></dd>
                  {t.category_label && <><dt>{C.F.category}</dt><dd>{t.category_label}</dd></>}
                </dl>
              </div>
            </section>
          )}

          {f.others.length > 0 && (
            <section className="stack stack--tight" aria-label={f.check === 'duplicate' ? C.OTHER_CHARGE : C.LAST_MONTH}>
              <h2 className="subhead">{f.check === 'duplicate' ? C.OTHER_CHARGE : C.LAST_MONTH}</h2>
              <div className="card"><Minis rows={f.others} /></div>
            </section>
          )}

          {f.earlier && (
            <section className="stack stack--tight" aria-label={f.earlier.heading}>
              <h2 className="subhead">{f.earlier.heading}</h2>
              <div className="card stack stack--tight"><p>{f.earlier.line}</p>{f.earlier.rows.length > 0 && <Minis rows={f.earlier.rows} />}</div>
            </section>
          )}
        </div>

        <div className="item__col">
          {canEdit && !f.done && f.expected && (
            <section className="card actions" aria-label={C.WHAT_DID_YOU_FIND}>
              <h2 className="subhead">{C.WHAT_DID_YOU_FIND}</h2>
              <div className="actions__row">
                <Button variant="quiet" icon={CircleCheck} onClick={() => setMode('expected')}>{C.EXPECTED}</Button>
                <Button variant="quiet" icon={Check} onClick={() => setMode('handled')}>{C.HANDLED}</Button>
                {f.status !== 'checking' && <Button variant="quiet" icon={Hourglass} onClick={() => setMode('checking')}>{C.STILL_CHECKING}</Button>}
              </div>
              <ul className="act-help">
                <li><b>{C.EXPECTED}:</b> {f.expected.help}</li>
                <li><b>{C.HANDLED}:</b> {C.HELP_HANDLED}</li>
                {f.status !== 'checking' && <li><b>{C.STILL_CHECKING}:</b> {C.HELP_CHECKING}</li>}
              </ul>
            </section>
          )}
          {canEdit && f.done && !doneLine && <div className="row-actions"><Button variant="quiet" icon={RotateCcw} busy={busy} onClick={() => void reopen()}>{C.REOPEN}</Button></div>}
          {f.viewer_line && <p className="small muted">{f.viewer_line}</p>}

          {f.related && (
            <section className="stack stack--tight" aria-label={C.RELATED_ITEM}>
              <h2 className="subhead">{C.RELATED_ITEM}</h2>
              <Link className="card fl related" to={`/inventory/${f.related.id}`}>
                <span className="fl__name">{f.related.name}</span>
                <span className="money money--m">{f.related.amount_cents !== null ? money(f.related.amount_cents) : ''}</span>
                <span className="fl__sub">{f.related.sub}</span>
              </Link>
            </section>
          )}

          <section className="stack stack--tight" aria-label={C.HISTORY}>
            <h2 className="subhead history-h"><History size={20} aria-hidden="true" />{C.HISTORY}</h2>
            <ul className="card history-list">
              {f.history.map((h) => {
                const Icon = WATCH_ICONS[h.icon] ?? Flag;
                return (
                  <li key={h.id}><Icon size={20} aria-hidden="true" />
                    <span className="stack history-item"><span>{h.text}</span>{h.note && <span className="note">"{h.note}"</span>}<span className="when">{stamp(h.at)}</span></span>
                  </li>
                );
              })}
            </ul>
          </section>
        </div>
      </div>

      <MarkSheet key={mode ?? 'closed'} flag={f} mode={mode} onClose={() => setMode(null)} onDone={(page) => void done(page)} />
    </div>
  );
}

export default FlagPage;
