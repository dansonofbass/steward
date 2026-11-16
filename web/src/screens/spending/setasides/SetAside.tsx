import { useQueryClient } from '@tanstack/react-query';
import { Calendar, CalendarClock, CircleAlert, CircleCheck, Info, Pencil, PiggyBank, TriangleAlert, Undo2 } from 'lucide-react';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useLocation, useParams } from 'react-router-dom';
import { useAccounts, useSetAside } from '../../../api/hooks';
import { editSetAside, invalidateSetAsides, replaceSetAside, skipDue, stopSetAside, unmatchPayment } from '../../../api/setasides';
import type { SetAsideBody, SetAsideDetail, SetAsideDue } from '../../../api/types';
import { useCanEdit } from '../../../book/BookContext';
import { Link, useNavigate } from '../../../book/links';
import { label } from '../../../lib/categories';
import { dollars, localYmd, money } from '../../../lib/format';
import { useRemoval } from '../../../lib/useRemoval';
import { Button } from '../../../ui/Button';
import { ConfirmSheet } from '../../../ui/ConfirmSheet';
import { Notice } from '../../../ui/Notice';
import { RemovalLine } from '../../../ui/RemovalLine';
import { Sheet } from '../../../ui/Sheet';
import { Skeleton } from '../../../ui/Skeleton';
import { TxnName, txnLabel } from '../../../ui/TxnName';
import { dayLabel, fillPct, joinNames } from '../model';
import { BackLink, PaceBar } from '../parts';
import * as C from './copy';
import { FirstLine } from './Moments';
import { dateText, draftFrom, dueSub, fill, findHref, fundLines, headLine, headState, notPaidFund, paymentMeta, replaceText, sourceNotes } from './model';
import { monthShortOf } from '../../cashflow/months';
import { SetAsideForm } from './SetAsideForm';
import { StateIcon } from './parts';
import { Sep } from '../../../ui/Sep';
import '../../transactions.css';
import '../spending.css';
import './setasides.css';

const DUE_ICON = { missed: CircleAlert, paid: CircleCheck, late: CircleCheck, skipped: CircleCheck, next: CalendarClock, upcoming: Calendar };

function DueRow({ d, asOf }: { d: SetAsideDue; asOf: string }) {
  const Icon = DUE_ICON[d.status];
  return (
    <div className={`sa-due is-${d.status}`} data-testid="sa-due">
      <Icon className="i" size={24} aria-hidden="true" />
      <span className="sa-due__when">{dateText(d.due_on)}</span>
      <span className="sa-due__sub">{dueSub(d, asOf)}</span>
      <span className="money money--m">{dollars(d.amount_cents)}</span>
    </div>
  );
}

/** The stored basis of an estimated one-off, with the item's own sources and age as the server sends them. */
function Basis({ r }: { r: SetAsideDetail }) {
  const e = r.estimate!;
  const age = e.age;
  const month = monthShortOf(r.due_month ?? 12);
  const notes = sourceNotes(e);
  return (
    <div className="card sa-basis" data-testid="sa-basis">
      <dl>
        <dt>{e.item === 'car' ? C.MODEL_YEAR : C.INSTALLED}</dt>
        <dd>{[e.installed_year ?? e.model_year, age === undefined || age === null ? null : age === 1 ? C.ONE_YEAR_OLD : fill(C.YEARS_OLD, { n: age })].filter((x) => x !== null).join(' · ')}</dd>
        {e.miles !== null && <><dt>{C.MILES}</dt><dd>{e.miles.toLocaleString('en-US')}</dd></>}
        <dt>{C.USUALLY_LASTS}</dt><dd>{fill(C.YEARS_RANGE, { lo: e.lifespan[0], hi: e.lifespan[1] })}</dd>
        <dt>{C.LIKELY_BY}</dt><dd>{fill(C.PLANNED_YEAR, { year: e.planned_year, month })}</dd>
        <dt>{C.TYPICAL_COST}</dt><dd>{fill(C.COST_RANGE, { lo: dollars(e.cost_range[0]), hi: dollars(e.cost_range[1]) })}</dd>
        <dt>{C.SET_ASIDE_FOR}</dt><dd>{fill(C.SET_ASIDE_FOR_VALUE, { amount: dollars(r.amount_cents), monthly: dollars(r.monthly_cents), from: dateText(r.first_month, true), to: `${month} ${r.due_year}` })}</dd>
      </dl>
      {notes.length > 0 && <ul className="sa-basis__src" data-testid="sa-sources">{notes.map((n) => <li key={n}>{n}</li>)}</ul>}
      <p className="sa-basis__rule">{C.BASIS_RULE}</p>
    </div>
  );
}

export function SetAside() {
  const { id = '0' } = useParams();
  const q = useSetAside(Number(id));
  const back = <BackLink to="/spending/setasides">{C.SETTING_ASIDE}</BackLink>;
  if (q.isError) return <div className="screen spending">{back}<Notice tone="error"><p>{q.error.message}</p></Notice></div>;
  if (!q.data) return <div className="screen spending" aria-busy="true">{back}<Skeleton lines={8} /></div>;
  return <Detail r={q.data} back={back} />;
}

function Detail({ r, back }: { r: SetAsideDetail; back: ReactNode }) {
  const asOf = r.as_of;
  const navigate = useNavigate();
  const loc = useLocation();
  const [first] = useState(() => (loc.state as { first?: boolean } | null)?.first === true);
  useEffect(() => { if (first) navigate(loc.pathname, { replace: true, state: null }); }, []); // eslint-disable-line react-hooks/exhaustive-deps -- once: a reload doesn't say it again
  const accounts = useAccounts();
  const qc = useQueryClient();
  const canEdit = useCanEdit();
  const [editing, setEditing] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Stop takes its own link away; the stopped line is said as it happens and focus goes to the name (THO-1).
  const removal = useRemoval();
  const stopped = r.archived_at !== null;
  const edit = canEdit && !stopped;
  const initial = useMemo(() => draftFrom(r), [r]);
  const e = r.estimate;

  // Invalidate even when a write fails: a stopped set-aside or a moved match must show as it now is.
  async function run(key: string, fn: () => Promise<unknown>, after?: () => void) {
    setBusy(key);
    setError(null);
    try { await fn(); after?.(); } catch (err) { setError((err as Error).message); } finally { await invalidateSetAsides(qc); setBusy(null); }
  }
  const save = (changes: Partial<SetAsideBody>) => run('save', () => editSetAside(r.id, changes), () => setEditing(false));
  const sharedWith = (accountId: number) => (r.account?.id === accountId ? r.account.shared_with : []);
  const fund = fundLines(r, asOf);
  const state = headState(r);
  const pct = fillPct(r.put_away_cents, r.state === 'short' || r.state === 'not_paid' ? r.installment_cents : r.should_cents, 0);
  const fundNote = notPaidFund(r);
  const openEdit = () => { setError(null); setEditing(true); };

  return (
    <div className="screen spending">
      {back}
      <header className="sa-head">
        <h1 ref={removal.anchor} tabIndex={-1}>{r.name}{r.is_estimate && <span className="tag tag--warn">{C.ESTIMATE}</span>}</h1>
        {first && <FirstLine nextDue={r.next_due} />}
        <div className="sp-total">
          <p className="sp-total__big" data-testid="sa-detail-head">{dollars(r.monthly_cents)} <span className="sp-of">{C.A_MONTH}</span></p>
          <p className="sp-total__line" data-testid="sa-detail-line">
            {headLine(r, asOf).map((p, i, all) => <span key={i} className="sp-total__part"><span>{p}</span>{i < all.length - 1 && <Sep className="sp-total__sep" />}</span>)}
          </p>
        </div>
        <p className={`sa-head__state is-${state.tone}`} data-testid="sa-detail-state">
          {r.paid ? <CircleCheck className="i" size={20} aria-hidden="true" /> : <StateIcon state={r.state} />}{state.text}
        </p>
        <RemovalLine removal={removal} />
        {stopped && !removal.line && <Notice><p>{fill(C.STOPPED, { date: dayLabel(localYmd(r.archived_at!)) })}</p></Notice>}
        {edit && (
          <div className="row-actions">
            <Button variant="quiet" icon={Pencil} onClick={openEdit}>{C.EDIT}</Button>
            <button type="button" className="link link--quiet" onClick={() => { setError(null); setStopping(true); }}>{C.STOP}</button>
          </div>
        )}
        {error && !editing && !stopping && <Notice tone="error">{error}</Notice>}
      </header>
      {r.paid && r.replace && (
        <Notice><div className="sa-first" data-testid="sa-replace">
          <Info className="i sa-first__icon" size={20} aria-hidden="true" />
          <div className="sa-first__body">
            <span className="eyebrow">{C.PAID_EYEBROW}</span>
            <span>{replaceText(r)}</span>
            {edit && (
              <div className="row-actions">
                {r.replace_offer && <Button busy={busy === 'replace'} onClick={() => void run('replace', async () => { const next = await replaceSetAside(r.id); await invalidateSetAsides(qc); navigate(`/spending/setasides/${next.id}`); })}>{C.START}</Button>}
                <button type="button" className="link" disabled={busy !== null} onClick={() => { setError(null); setStopping(true); }}>{C.NO_ARCHIVE}</button>
              </div>
            )}
            <span className="small muted">{C.REPLACE_NOTE}</span>
          </div>
        </div></Notice>
      )}
      <div className="sa-cols">
        <div className="stack sp-side">
          {r.is_estimate && e ? (
            <section className="stack" aria-labelledby="sa-basis-h">
              <div className="section-head"><h2 id="sa-basis-h">{C.WHERE_FROM}</h2></div>
              <Basis r={r} />
              {edit && (
                <div className="sa-est__edit">
                  {[C.CHANGE_YEAR, C.CHANGE_AMOUNT, C.INSTALLED_OTHER].map((t) => (
                    <button key={t} type="button" className="link" onClick={openEdit}><Pencil className="i" size={16} aria-hidden="true" />{t}</button>
                  ))}
                </div>
              )}
            </section>
          ) : (
            <section className="stack" aria-labelledby="sa-dues-h">
              <div className="section-head"><h2 id="sa-dues-h">{C.WHEN_DUE}</h2>{r.kind === 'twice_yearly' && <span className="small muted">{C.TWO_INSTALLMENTS}</span>}</div>
              <div className="card sa-dues">{r.dues.map((d) => <DueRow key={d.due_on} d={d} asOf={asOf} />)}</div>
              {r.kind !== 'one_off' && <p className="small muted">{fill(C.SCHEDULE_NOTE, { monthly: dollars(r.monthly_cents) })}</p>}
            </section>
          )}
          {r.state === 'not_paid' && r.missed_due && !stopped && (
            <Notice tone="warn"><div className="sa-first" data-testid="sa-not-paid">
              <TriangleAlert className="i sa-first__icon" size={20} aria-hidden="true" />
              <div className="sa-first__body">
                <span className="eyebrow">{C.NO_PAYMENT_EYEBROW}</span>
                <span>{r.payee_name ? fill(C.NO_PAYMENT_BODY, { payee: r.payee_name, label: label(r.category ?? ''), date: dayLabel(r.missed_due) }) : fill(C.NO_PAYMENT_BODY_NO_PAYEE, { date: dayLabel(r.missed_due) })}</span>
                {edit && (
                  <div className="row-actions">
                    <Link className="btn btn--quiet" to={findHref(r)}><span className="btn__content"><span>{C.FIND_PAYMENT}</span></span></Link>
                    <button type="button" className="link link--quiet" disabled={busy !== null} aria-label={fill(C.WAS_NOT_DUE_FOR, { date: dayLabel(r.missed_due) })}
                      onClick={() => void run('skip', () => skipDue(r.id, r.missed_due!))}>{C.WAS_NOT_DUE}</button>
                  </div>
                )}
              </div>
            </div></Notice>
          )}
          <section className="stack" aria-labelledby="sa-fund-h">
            <div className="section-head"><h2 id="sa-fund-h">{C.PUT_AWAY}</h2>{edit && <button type="button" className="link sa-link--s" onClick={openEdit}>{r.account ? C.CHANGE_ACCOUNT : C.LINK_ACCOUNT}</button>}</div>
            <div className="card sa-fund" data-testid="sa-fund">
              {r.account ? (
                <>
                  <div className="sa-fund__who"><span className="strong"><PiggyBank className="i" size={20} aria-hidden="true" />{r.account.name}</span>
                    {r.account.stale && r.account.as_of && <span className="small muted">{fill(C.BALANCE_FROM, { date: dayLabel(r.account.as_of) })}</span>}</div>
                  <p className={`sa-fund__line is-${fund.tone}`}><span>{fund.lead}</span><span className="muted">{` · ${fund.detail}`}</span></p>
                  <p className="sa-fund__nums">{dollars(r.put_away_cents)} <span className="sp-of">{C.PUT_AWAY_WORD}</span></p>
                  <PaceBar fill={pct} tone={fund.tone === 'soon' ? 'soon' : fund.tone === 'behind' ? 'behind' : r.should_cents > 0 ? 'track' : 'none'} today={null} />
                  <p className="sa-fund__line"><span className="muted">{fund.context}</span></p>
                  {fundNote && <p className="small muted">{fundNote}</p>}
                  {r.account.shared_with.length > 0 && <p className="small muted">{fill(C.SHARED_NOTE, { names: joinNames(r.account.shared_with) })}</p>}
                </>
              ) : <p className="muted">{C.NO_ACCOUNT}</p>}
            </div>
          </section>
        </div>
        <section className="stack" aria-labelledby="sa-paid-h">
          <div className="section-head"><h2 id="sa-paid-h">{C.PAID_FROM_IT}</h2><span className="small muted">{r.payments.length === 1 ? C.ONE_MATCHED : fill(C.N_MATCHED, { n: r.payments.length })}</span></div>
          {r.payments.length === 0 ? <p className="muted">{C.NONE_MATCHED}</p> : (
            <div className="card sa-pays">
              {r.payments.map((p) => {
                const payee = txnLabel(p);
                return (
                  <div className="txn" key={p.transaction_id} data-testid="sa-payment">
                    <span className={`txn__name${p.merchant || p.nickname ? '' : ' is-raw'}`}><TxnName t={p} /></span>
                    <span className="money money--m money--out">{money(p.amount_cents)}</span>
                    <span className="txn__meta"><span>{paymentMeta(p, r.kind === 'one_off' ? r.name : undefined)}</span>
                      {edit && (
                        <button type="button" className="link link--quiet" disabled={busy !== null} aria-label={fill(C.NOT_THIS_ONE_FOR, { date: dayLabel(p.posted_at), payee })}
                          onClick={() => void run(`un${p.transaction_id}`, () => unmatchPayment(p.transaction_id))}><Undo2 className="i" size={16} aria-hidden="true" />{C.NOT_THIS_ONE}</button>
                      )}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
          <p className="small muted">{C.PAID_NOTE}</p>
        </section>
      </div>
      <Sheet open={editing} onClose={() => setEditing(false)} title={`${C.EDIT} ${r.name}`}>
        <SetAsideForm initial={initial} asOf={asOf} accounts={accounts.data?.accounts ?? []} busy={busy === 'save'} error={error} submitLabel={C.SAVE}
          editing={{ id: r.id, isEstimate: r.is_estimate }} onSubmit={(_, changes) => void save(changes)} onCancel={() => setEditing(false)} sharedWith={sharedWith} />
      </Sheet>
      <ConfirmSheet open={stopping} title={fill(C.STOP_TITLE, { name: r.name })} body={C.STOP_BODY} action={C.STOP_ACTION} variant="danger" busy={busy === 'stop'} error={error}
        onConfirm={() => void run('stop', () => stopSetAside(r.id), () => { removal.removed(fill(C.STOPPED, { date: dayLabel(localYmd(new Date().toISOString())) })); setStopping(false); })}
        onClose={() => setStopping(false)} returnTo={removal.returnTo} />
    </div>
  );
}

export default SetAside;
