import { useQueryClient } from '@tanstack/react-query';
import { ArchiveRestore, ChevronLeft, ChevronRight, CircleCheck, CircleDashed, Download, Eye, EyeOff, FileText, History, Image, KeyRound, Mail, MapPin, MessageSquareText, Paperclip, Pencil, Phone, Plus, Trash2 } from 'lucide-react';
import { Fragment, useState, type ReactNode } from 'react';
import { useParams } from 'react-router-dom';
import { useBook, useCanEdit } from '../../book/BookContext';
import { Link } from '../../book/links';
import { dateLabel, localYmd, money } from '../../lib/format';
import { TRY_AGAIN } from '../../lib/copy';
import { useRemoval } from '../../lib/useRemoval';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { ConfirmSheet } from '../../ui/ConfirmSheet';
import { RemovalLine } from '../../ui/RemovalLine';
import { Skeleton } from '../../ui/Skeleton';
import { failure } from '../settings/shared';
import { editItem, fileHref, refreshInventory, removeFile, reopenItem, revealNumber, useItem, type FileRow, type ItemDetail } from './api';
import { ChangeDetails, ChangeText } from './ChangeLine';
import * as C from './copy';
import { fill, longDate, ordinal, shortDate } from './format';
import { SourceMark, StatusMark } from './marks';
import './inventory.css';

const d = (it: ItemDetail, k: string) => it.details[k] as string | number | undefined;

function RefLink({ r }: { r: { id: number; label: string } | null }) {
  return r ? <Link to={`/inventory/${r.id}`}>{r.label}</Link> : <>{C.NOT_KNOWN}</>;
}

function Names({ rows }: { rows: { id: number; name: string }[] }) {
  return <>{rows.map((r, i) => <span key={r.id}>{i > 0 && ', '}<Link to={`/inventory/${r.id}`}>{r.name}</Link></span>)}</>;
}

function Facts({ it, numberRow }: { it: ItemDetail; numberRow: (label: string) => ReactNode }) {
  const today = new Date();
  const owner = <>{it.owner_label}{it.joint_names && <span className="small muted"> ({it.joint_names})</span>}</>;
  const login = <><KeyRound size={20} aria-hidden="true" />{it.login_kept_in ?? C.NO_LOGIN}</>;
  const rows: [string, ReactNode][] = [];
  if (it.kind === 'account') {
    rows.push([it.type === 'property' ? C.F.where : C.F.institution, it.institution ?? C.NOT_KNOWN], [C.F.type, it.type_label ?? C.NOT_KNOWN]);
    rows.push(['__number__', null]);
    rows.push([C.F.owner, owner], [C.F.dataFrom, <SourceMark source={it.data_source} />], [C.F.loginKeptIn, login]);
    if (d(it, 'floor_cents') !== undefined) rows.push([C.F.floor, <span className="money">{money(Number(d(it, 'floor_cents')))}</span>]);
    if (it.money_in_here.length) rows.push([C.F.moneyInHere, <Names rows={it.money_in_here} />]);
    if (it.paid_from_here.length) rows.push([C.F.paidFromHere, <Names rows={it.paid_from_here} />]);
  } else if (it.kind === 'income') {
    const freq = String(d(it, 'frequency') ?? 'monthly');
    rows.push([C.F.amount, <><span className="money">{money(Number(d(it, 'amount_cents') ?? 0))}</span> <span className="small muted">{C.PER_WORDS[freq]}</span></>]);
    if (d(it, 'usual_day')) rows.push([C.F.usuallyArrives, fill(C.AROUND_THE, { day: ordinal(Number(d(it, 'usual_day'))) })]);
    rows.push([C.F.landsIn, <RefLink r={it.refs.lands_in_id} />]);
    if (it.matched) rows.push([C.F.matchedBy, <span className="raw">{it.matched.match_text}</span>]);
    rows.push([C.F.owner, owner]);
  } else if (it.kind === 'insurance') {
    rows.push(['__number__', null]);
    const freq = d(it, 'frequency') as string | undefined;
    if (d(it, 'amount_cents') !== undefined) {
      rows.push([C.F.premium, <><span className="money">{money(Number(d(it, 'amount_cents')))}</span> {freq ? (C.FREQUENCY_LABELS[freq] ?? freq).toLowerCase() : ''}{d(it, 'usual_day') ? `, ${fill(C.AROUND_THE, { day: ordinal(Number(d(it, 'usual_day'))) }).toLowerCase()}` : ''}</>]);
    }
    rows.push([C.F.paidFrom, <><RefLink r={it.refs.paid_from_id} />{it.matched?.last_paid && <span className="small muted"> · {fill(C.LAST_PAID, { date: dateLabel(it.matched.last_paid, today) })}</span>}</>]);
    if (it.type === 'long_term_care' && d(it, 'benefit_cents') != null) {
      const per = d(it, 'benefit_per') === 'month' ? C.LTC.perMonth.toLowerCase() : C.LTC.perDay.toLowerCase();
      rows.push([C.F_LTC.benefit, <><span className="money">{money(Number(d(it, 'benefit_cents')))}</span> {per}</>]);
      rows.push([C.F_LTC.waiting, d(it, 'waiting_days') != null ? fill(C.F_LTC.days, { n: String(d(it, 'waiting_days')) }) : C.NOT_KNOWN]);
      rows.push([C.F_LTC.pool, d(it, 'pool_cents') != null ? <span className="money">{money(Number(d(it, 'pool_cents')))}</span>
        : d(it, 'benefit_years') != null ? fill(C.F_LTC.yearsOf, { n: String(d(it, 'benefit_years')) }) : C.NOT_KNOWN]);
      rows.push([C.F_LTC.rider, d(it, 'rider_bp') != null ? fill(C.F_LTC.riderPct, { pct: String(Number(d(it, 'rider_bp')) / 100) }) : C.F_LTC.none]);
    }
    rows.push([C.F.renewal, d(it, 'renewal_on') ? longDate(String(d(it, 'renewal_on'))) : C.NOT_KNOWN], [C.F.owner, owner], [C.F.loginKeptIn, login]);
  } else if (it.kind === 'document') {
    rows.push([C.F.type, it.type_label ?? C.NOT_KNOWN], [C.F.signed, d(it, 'signed_on') ? longDate(String(d(it, 'signed_on'))) : C.NOT_KNOWN]);
    rows.push([C.F.owner, owner], [C.F.preparedBy, <RefLink r={it.refs.prepared_by_id} />]);
    rows.push([C.F.scan, it.files.length ? <><FileText size={20} aria-hidden="true" />{C.ATTACHED}</> : C.NOT_ATTACHED]);
  } else {
    rows.push([C.F.role, it.type_label ?? C.NOT_KNOWN], [C.F.firm, it.institution ?? C.NOT_KNOWN]);
    if (d(it, 'phone')) rows.push([C.F.phone, <><Phone size={20} aria-hidden="true" /><a href={`tel:${String(d(it, 'phone')).replace(/[^\d+]/g, '')}`}>{String(d(it, 'phone'))}</a></>]);
    if (d(it, 'email')) rows.push([C.F.email, <><Mail size={20} aria-hidden="true" /><a href={`mailto:${String(d(it, 'email'))}`}>{String(d(it, 'email'))}</a></>]);
    const linked = [...it.linked_items, ...it.looks_after.filter((r) => !it.linked_items.some((l) => l.id === r.id)).map((r) => ({ id: r.id, name: r.label }))];
    if (linked.length) rows.push([C.F.linkedItems, <Names rows={linked} />]);
  }
  rows.push([C.F.added, it.added_line]);
  return (
    <dl className="card ifacts">
      {rows.map(([label, value]) => label === '__number__'
        ? <Fragment key="number">{numberRow(it.kind === 'insurance' ? C.F.policyNumber : C.F.accountNumber)}</Fragment>
        : <Fragment key={label}><dt>{label}</dt><dd>{value}</dd></Fragment>)}
    </dl>
  );
}

// Keyed by id so a revealed number, an error or a pending removal never carries over to the next item.
export function ItemPage() {
  const { id = '' } = useParams();
  return <ItemBody key={id} itemId={Number(id)} />;
}

function ItemBody({ itemId }: { itemId: number }) {
  const q = useItem(itemId);
  const canEdit = useCanEdit();
  const slug = useBook()?.slug ?? 'ours';
  const qc = useQueryClient();
  const [number, setNumber] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState<FileRow | null>(null);
  // A removed file says so under Files, and focus goes to the Files heading rather than the gone row (THO-1).
  const removal = useRemoval();

  if (q.isPending) return <div className="screen" aria-busy="true"><Skeleton lines={8} /></div>;
  if (q.isError) return <div className="screen"><Notice tone="error"><p>{q.error.message}</p><Button variant="quiet" onClick={() => q.refetch()}>{TRY_AGAIN}</Button></Notice></div>;
  const it = q.data;
  const today = new Date();

  async function act(fn: () => Promise<unknown>, done?: () => void) {
    setBusy(true);
    setError(null);
    removal.clear();
    try {
      await fn();
      done?.();
      await refreshInventory(qc);
    } catch (e) {
      setError(failure(e));
    } finally {
      setBusy(false);
    }
  }
  const numberRow = (label: string) => (
    <>
      <dt>{label}</dt>
      <dd className="num-row">
        <span>{number ?? (it.last4 ? `••${it.last4}` : C.NOT_KNOWN)}</span>
        {it.has_full_number && !number && <Button variant="quiet" icon={Eye} busy={busy} onClick={() => void act(async () => setNumber((await revealNumber(it.id)).number))}>{C.SHOW}</Button>}
        {number && <Button variant="quiet" icon={EyeOff} onClick={() => setNumber(null)}>{C.HIDE}</Button>}
      </dd>
    </>
  );
  const head = it.kind === 'document' ? `${it.owner_label} · ${it.type_word ?? ''}`
    : it.kind === 'income' ? it.owner_label
      : [it.institution && `${it.institution}${it.last4 ? ` ••${it.last4}` : ''}`, it.owner_label].filter(Boolean).join(' · ');
  const open = it.status !== 'closed';

  return (
    <div className="screen item-page">
      <header className="page-head">
        <Link className="link back" to="/inventory"><ChevronLeft className="i" size={20} aria-hidden="true" />{C.BACK_TO_INVENTORY}</Link>
        <p className="eyebrow">{C.KIND_LABELS[it.kind]}{it.type_word ? ` · ${it.type_word}` : ''}</p>
        <div className="page-head__row">
          <h1>{it.name}</h1>
          {canEdit && open && (
            <div className="row-actions">
              <Link className="btn btn--quiet" to={`/inventory/${it.id}/attach`}><span className="btn__content"><Paperclip size={20} aria-hidden="true" /><span>{C.ATTACH_A_FILE}</span></span></Link>
              <Link className="btn btn--quiet" to={`/inventory/${it.id}/edit`}><span className="btn__content"><Pencil size={20} aria-hidden="true" /><span>{C.EDIT}</span></span></Link>
            </div>
          )}
          {canEdit && !open && <Button variant="quiet" icon={ArchiveRestore} busy={busy} onClick={() => void act(() => reopenItem(it.id))}>{C.REOPEN}</Button>}
        </div>
        {it.kind !== 'contact' && <p className="row-actions"><StatusMark status={it.status} />{it.data_source && <SourceMark source={it.data_source} />}<span className="small muted">{head}</span></p>}
      </header>

      {error && <Notice tone="error">{error}</Notice>}
      {!open && it.closed_on && <Notice>{fill(C.CLOSED_LINE, { date: dateLabel(it.closed_on, today) })}{it.closed_reason ? ` ${it.closed_reason}` : ''}</Notice>}
      {it.status === 'needs_checking' && (
        <Notice tone="warn">
          <span className="stack stack--tight">
            <span><CircleDashed size={20} aria-hidden="true" /> <strong>{C.WHY_CHECKING}</strong> <span>{it.check_reason ?? ''}</span></span>
            <span className="small muted">{C.TO_CONFIRM_BY_KIND[it.kind]}</span>
            {canEdit && (
              <span className="row-actions">
                <Link className="btn btn--quiet" to={`/inventory/${it.id}/attach`}><span className="btn__content"><Paperclip size={20} aria-hidden="true" /><span>{C.ATTACH_A_FILE}</span></span></Link>
                <Button icon={CircleCheck} busy={busy} onClick={() => void act(() => editItem(it.id, { status: 'confirmed' }))}>{C.MARK_CONFIRMED}</Button>
              </span>
            )}
          </span>
        </Notice>
      )}

      <div className="item">
        <div className="item__col">
          {it.kind === 'document' && d(it, 'original_kept_in') && (
            <div className="key-callout"><MapPin size={20} aria-hidden="true" /><div className="stack stack--tight"><span className="eyebrow">{C.F.originalKeptIn}</span><span className="lede">{String(d(it, 'original_kept_in'))}</span></div></div>
          )}
          {it.kind === 'account' && (
            <section className="balance" aria-label={C.BALANCE}>
              <span className="eyebrow">{C.BALANCE}</span>
              {it.balance ? <><span className="money money--xl">{money(it.balance.cents)}</span><span className="small muted">{it.balance.line}</span></> : <span className="muted">{C.NO_BALANCE}</span>}
            </section>
          )}
          {it.kind === 'account' && it.holdings && it.holdings.rows.length > 0 && (
            <section className="stack" aria-label={C.HOLDINGS_ON.replace('{date}', shortDate(it.holdings.as_of))}>
              <h2 className="subhead">{C.HOLDINGS_ON.replace('{date}', shortDate(it.holdings.as_of))}</h2>
              <ul className="plain">
                {it.holdings.rows.map((h, i) => <li key={i} className="sec-h"><span>{h.symbol || h.name}</span><span className="money money--m">{money(h.value_cents)}</span></li>)}
              </ul>
            </section>
          )}
          <section className="stack" aria-label={C.DETAILS}>
            <h2 className="subhead">{C.DETAILS}</h2>
            <Facts it={it} numberRow={numberRow} />
          </section>
          {it.kind === 'account' && it.transactions.length > 0 && (
            <section className="stack" aria-label={C.RECENT_TRANSACTIONS}>
              <div className="sec-h"><h2>{C.RECENT_TRANSACTIONS}</h2><Link className="link" to={`/transactions?account_id=${it.account_id}&dates=all`}>{C.ALL_IN_TRANSACTIONS}<ChevronRight size={20} aria-hidden="true" /></Link></div>
              <div className="card">
                {it.transactions.map((t) => (
                  <div key={t.id} className="txn"><span className="txn__name">{t.name}</span><span className={`money money--m${t.amount_cents > 0 ? ' money--in' : ''}`}>{money(t.amount_cents, { sign: t.amount_cents > 0 ? 'always' : 'never' })}</span><span className="txn__meta">{dateLabel(t.posted_at, today)}</span></div>
                ))}
              </div>
            </section>
          )}
          {it.matched && it.matched.rows.length > 0 && (
            <section className="stack stack--tight" aria-label={it.matched.heading}>
              <h3>{it.matched.heading}</h3>
              <div className="card">
                {it.matched.rows.map((r, i) => (
                  <div key={`${r.posted_at}-${r.amount_cents}-${i}`} className="txn"><span className="txn__name">{dateLabel(r.posted_at, today)}{r.note && <span className="small muted"> ({r.note})</span>}</span><span className={`money money--m${r.amount_cents > 0 ? ' money--in' : ''}`}>{money(Math.abs(r.amount_cents))}</span></div>
                ))}
              </div>
            </section>
          )}
        </div>

        <div className="item__col">
          <section className="stack" aria-label={C.FILES}>
            <div className="sec-h"><h2 ref={removal.anchor} tabIndex={-1}><Paperclip size={20} aria-hidden="true" />{C.FILES}</h2>{canEdit && open && <Link className="link" to={`/inventory/${it.id}/attach`}><Plus size={20} aria-hidden="true" />{C.ATTACH}</Link>}</div>
            <RemovalLine removal={removal} />
            <div className="card files">
              {it.files.length === 0 && <p className="small muted">{C.NO_FILES}</p>}
              {it.files.map((f) => {
                const Icon = f.content_type.startsWith('image/') ? Image : FileText;
                return (
                  <div key={f.id} className="file">
                    <Icon size={20} aria-hidden="true" />
                    <div className="file__main"><span className="file__name">{f.name}</span><span className="file__sub">{f.label} · {f.size_label} · {dateLabel(f.uploaded_on, today)}{f.uploaded_by ? ` by ${f.uploaded_by}` : ''}</span></div>
                    {canEdit ? (
                      <>
                        <a className="btn btn--quiet" href={fileHref(slug, f.id)} download={f.name}><span className="btn__content"><Download size={20} aria-hidden="true" /><span>{C.DOWNLOAD}{' '}<span className="sr-only">{f.name}</span></span></span></a>
                        <button className="btn btn--quiet" type="button" onClick={() => setRemoving(f)}><span className="btn__content"><Trash2 size={20} aria-hidden="true" /><span>{C.REMOVE}{' '}<span className="sr-only">{f.name}</span></span></span></button>
                      </>
                    ) : (
                      <a className="btn btn--quiet" href={fileHref(slug, f.id)} download={f.name}><span className="btn__content"><Download size={20} aria-hidden="true" /><span>{C.DOWNLOAD}</span></span></a>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
          <section className="stack" aria-label={C.NOTES}>
            <div className="sec-h"><h2><MessageSquareText size={20} aria-hidden="true" />{C.NOTES}</h2>{canEdit && open && <Link className="link" to={`/inventory/${it.id}/edit`}><Pencil size={20} aria-hidden="true" />{C.EDIT}</Link>}</div>
            <div className="card note-box">{it.notes ?? <span className="muted">{C.NO_NOTES}</span>}</div>
          </section>
          <section className="stack" aria-label={C.HISTORY}>
            <div className="sec-h"><h2><History size={20} aria-hidden="true" />{C.HISTORY}</h2><Link className="link" to="/settings/changes">{C.CHANGE_RECORD}<ChevronRight size={20} aria-hidden="true" /></Link></div>
            <ul className="hist">
              {it.history.map((h) => (
                <li key={h.id}><span className="hist__when">{dateLabel(localYmd(h.at), today)}</span><span className="hist__what"><ChangeText row={h} /><ChangeDetails row={h} /></span></li>
              ))}
            </ul>
          </section>
        </div>
      </div>

      <ConfirmSheet open={removing !== null} onClose={() => setRemoving(null)} title={removing ? fill(C.REMOVE_FILE_TITLE, { name: removing.name }) : ''}
        body={C.REMOVE_FILE_BODY} action={C.REMOVE} cancel={C.KEEP_IT} busy={busy} error={error}
        onConfirm={() => { const f = removing; if (f) void act(() => removeFile(f.id), () => { removal.removed(fill(C.FILE_REMOVED, { name: f.name })); setRemoving(null); }); }}
        returnTo={removal.returnTo} />
    </div>
  );
}

export default ItemPage;
