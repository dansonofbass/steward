import { useQueryClient } from '@tanstack/react-query';
import { ArrowDownLeft, CalendarClock, ChevronRight, PiggyBank } from 'lucide-react';
import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAccounts, useSpending } from '../../api/hooks';
import { undoToken } from '../../api/profile';
import { invalidateSetAsides, unmatchPayment } from '../../api/setasides';
import type { EverydayRow, SpendingMonth } from '../../api/types';
import { useCanEdit } from '../../book/BookContext';
import { Link } from '../../book/links';
import { label } from '../../lib/categories';
import { dollars } from '../../lib/format';
import { overLine } from '../../lib/spendingLine';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { UndoToast } from '../../ui/UndoToast';
import { UntypedNotice } from '../../ui/UntypedNotice';
import { drillHref, monthLong } from '../cashflow/months';
import { OverLineView } from '../home/OverLine';
import * as C from './copy';
import { FixedLine } from './FixedLine';
import { dayLabel, fill, fillPct, headFigure, headParts, inOutLine, occasionalLine, paceScale, paceText, paceTone, setAsideLine, todayPct, unsortedText } from './model';
import { MonthSwitcher, PaceBar, Pills, Refused, waitingTitle } from './parts';
import { stateLine, stateTone, summaryRow } from './setasides/model';
import { StateIcon } from './setasides/parts';
import { TargetCheck, type Answered } from './TargetCheck';
import { Sep } from '../../ui/Sep';
import './setasides/setasides.css';
import './spending.css';

const chevron = <ChevronRight className="i sp-pace__chev" size={20} aria-hidden="true" />;

function PaceRow({ r, m, scale, canEdit }: { r: EverydayRow; m: SpendingMonth; scale: number; canEdit: boolean }) {
  const tone = paceTone(r, m.current);
  return (
    <div className="sp-pace" data-testid="pace-row" data-category={r.category}>
      <Link className="sp-pace__name sp-pace__go" to={`/spending/${r.category}?month=${m.month}`}>{label(r.category)}</Link>
      <span className="sp-pace__amt">
        <span className="money money--m">{dollars(r.spent_cents)}</span>
        {r.target_cents !== null && <> <span className="muted">{fill(C.OF, { amount: dollars(r.target_cents) })}</span></>}
      </span>
      <PaceBar fill={fillPct(r.spent_cents, r.target_cents, scale)} tone={tone} today={r.target_cents !== null ? todayPct(m) : null} />
      <span className={`sp-pace__state is-${tone}`}>
        {paceText(r, m.current)}
        {r.state === 'none' && canEdit && (
          <Link className="link sp-pace__set" to="/spending/targets">{C.SET_ONE}<ChevronRight className="i" size={16} aria-hidden="true" /></Link>
        )}
      </span>
      {chevron}
    </div>
  );
}

function UnsortedRow({ m, scale, canEdit }: { m: SpendingMonth; scale: number; canEdit: boolean }) {
  const n = m.not_sorted;
  const body = (
    <>
      <span className="sp-pace__name">{label('uncategorized')}</span>
      <span className="sp-pace__amt"><span className="money money--m">{dollars(n.cents)}</span></span>
      <PaceBar fill={fillPct(n.cents, null, scale)} tone="none" today={null} unsorted />
      <span className="sp-pace__state is-none">
        {unsortedText(n.count)}
        {canEdit && <span className="link">{C.SORT_THEM}<ChevronRight className="i" size={16} aria-hidden="true" /></span>}
      </span>
    </>
  );
  // Sorting is a manager's (Review): a viewer reads the row but it opens nothing.
  return canEdit
    ? <Link className="sp-pace sp-pace--unsorted" to="/review" data-testid="unsorted-row">{body}{chevron}</Link>
    : <div className="sp-pace sp-pace--unsorted" data-testid="unsorted-row">{body}</div>;
}

/** "Not this one?" is offered on a paid row unless its set-aside was stopped (`archived`); a refused undo (409 "That set-aside
 *  was stopped.") still shows the server's words. */
function PaidRows({ m, canEdit }: { m: SpendingMonth; canEdit: boolean }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function undo(id: number) {
    setBusy(true); setError(null);
    try { await unmatchPayment(id); await invalidateSetAsides(qc); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return (
    <section className="stack" aria-labelledby="sp-paid-h">
      <div className="section-head"><h2 id="sp-paid-h">{C.PAID_FROM}</h2><span className="small muted">{C.NOT_AGAINST}</span></div>
      <div className="card sp-fixeds">
        {m.set_aside!.paid.map((p) => (
          <div key={p.transaction_id} className="sp-fixed sa-paid" data-testid="sa-paid-row">
            <PiggyBank className="i" size={24} aria-hidden="true" />
            <span className="sp-fixed__name">{p.name}</span>
            <span className="sp-fixed__sub">
              {fill(p.late ? C.PAID_FROM_SUB_LATE : C.PAID_FROM_SUB, { payee: p.payee, date: dayLabel(p.posted_at) })}
              {canEdit && !p.archived && <> · <button type="button" className="link" disabled={busy} aria-label={`${C.NOT_THIS_ONE_Q} ${p.name}, ${p.payee}, ${dayLabel(p.posted_at)}`} onClick={() => void undo(p.transaction_id)}>{C.NOT_THIS_ONE_Q}</button></>}
            </span>
            <span className="money money--m">{dollars(p.cents)}</span>
            <Link to={`/spending/setasides/${p.set_aside_id}`} aria-label={`${C.OPEN_SET_ASIDE}: ${p.name}`}><ChevronRight className="i" size={20} aria-hidden="true" /></Link>
          </div>
        ))}
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      <p className="small muted">{C.PAID_FROM_NOTE}</p>
    </section>
  );
}

function SetAsideSection({ m }: { m: SpendingMonth }) {
  const s = m.set_aside!;
  const row = summaryRow(s);
  return (
    <section className="stack" aria-labelledby="sp-sa-h">
      <div className="section-head"><h2 id="sp-sa-h">{C.SETTING_ASIDE}</h2><span className="small muted">{fill(C.SA_THIS_MONTH, { amount: dollars(s.monthly_cents) })}</span></div>
      <div className="card sa-rows">
        <Link className="sa-row sa-row--line is-sum" to="/spending/setasides" data-testid="sa-summary">
          <PiggyBank className="i" size={24} aria-hidden="true" />
          <span className="sa-row__name">{row.name}</span>
          <span className="sa-row__sub">{row.sub}</span>
          <span className="money money--m">{dollars(s.monthly_cents)}</span>
          <ChevronRight className="i" size={20} aria-hidden="true" />
        </Link>
        {s.needs_look.map((r) => (
          <Link key={r.id} className={`sa-row sa-row--line is-${stateTone(r.state)}`} to={`/spending/setasides/${r.id}`} data-testid="sa-look">
            <StateIcon state={r.state} />
            <span className="sa-row__name">{r.name}</span>
            <span className="sa-row__sub">{stateLine(r)}</span>
            <span className="money money--m">{dollars(r.monthly_cents)}</span>
            <ChevronRight className="i" size={20} aria-hidden="true" />
          </Link>
        ))}
      </div>
      <p className="small muted">{C.SA_NOTE}</p>
    </section>
  );
}

export function Spending() {
  const [sp] = useSearchParams();
  const month = sp.get('month');   // none: the server's month, never the browser's
  const q = useSpending(month);
  const accounts = useAccounts();
  const canEdit = useCanEdit();
  const qc = useQueryClient();
  const [answered, setAnswered] = useState<Answered | null>(null);
  async function undoAnswer() {
    const t = answered?.token;
    setAnswered(null);
    if (t) await undoToken(t).catch(() => null);   // a refused undo (409, 410): the month as it is now is what shows
    await qc.invalidateQueries({ queryKey: ['spending'] });
  }
  const back = <Pills on="month" />;
  const title = <h1>{waitingTitle(month)}</h1>;
  if (q.isError) return <div className="screen spending">{back}{title}<Refused error={q.error} month={month} retry={() => void q.refetch()} /></div>;
  if (!q.data) return <div className="screen spending" aria-busy="true">{back}{title}<Skeleton lines={8} /></div>;
  const m = q.data;
  const scale = paceScale(m);
  const occ = occasionalLine(m);
  const sal = setAsideLine(m);
  const io = inOutLine(m);
  const figure = headFigure(m);
  const parts = headParts(m);
  const flexLine = overLine(m);
  return (
    <div className="screen spending">
      {back}
      <header className="sp-head">
        <MonthSwitcher month={m.month} earliest={m.earliest} current={m.current} />
        <div className="sp-total">
          <p className="sp-total__big" data-testid="sp-total">
            {figure.amount} <span className="sp-of">{figure.tail}</span>
          </p>
          <p className="sp-total__line" data-testid="sp-line">
            {/* Each separator ends the part before it, so a wrapped line never starts with one. */}
            {parts.map((p, i) => (
              <span key={i} className="sp-total__part">
                <span className={i === 0 ? 'sp-total__lead' : undefined}>{p}</span>
                {i < parts.length - 1 && <Sep className="sp-total__sep" />}
              </span>
            ))}
          </p>
          {occ && <p className="small muted">{occ}</p>}
          {sal && <p className="small muted" data-testid="sp-set-aside-line">{sal}</p>}
          {io && <p className="small muted" data-testid="sp-in-out">{io}</p>}
        </div>
      </header>
      <UntypedNotice accounts={accounts.data?.accounts} where="spending" />
      {canEdit && m.target_check && <TargetCheck key={m.target_check.category} check={m.target_check} onAnswered={setAnswered} />}
      {answered && <UndoToast text={answered.text} onUndo={() => void undoAnswer()} onClose={() => setAnswered(null)} />}
      <div className="sp-cols">
        <section className="stack" aria-labelledby="sp-every-h" id="flexible">
          <div className="section-head"><h2 id="sp-every-h">{C.FLEXIBLE}</h2><span className="small muted">{C.BY_TARGET}</span></div>
          {flexLine && <OverLineView line={flexLine} />}
          {m.everyday.length === 0 && m.not_sorted.count === 0
            ? <p className="muted">{fill(C.NO_FLEXIBLE, { month: monthLong(m.month) })}</p>
            : (
              <div className="card sp-paces">
                {m.everyday.map((r) => <PaceRow key={r.category} r={r} m={m} scale={scale} canEdit={canEdit} />)}
                {m.not_sorted.count > 0 && <UnsortedRow m={m} scale={scale} canEdit={canEdit} />}
              </div>
            )}
          {m.current && m.day !== null && (
            <p className="sp-pace-key">{C.PACE_KEY_A}{' '}<span className="sp-pace-key__today" aria-hidden="true" />{' '}{fill(C.PACE_KEY_B, { date: dayLabel(m.as_of), day: m.day, days: m.days })}</p>
          )}
          <p className="small muted">{C.FOOTNOTE}</p>
        </section>
        <div className="stack sp-side">
          {m.fixed.length > 0 && (
            <section className="stack" aria-labelledby="sp-fixed-h" id="fixed">
              <div className="section-head">
                <h2 id="sp-fixed-h">{C.FIXED_COSTS}</h2>
                {/* Nothing expected yet (a new household's first month): no "$0 expected" over real payments. */}
                {m.head.fixed_summary !== 'none' && m.head.fixed_expected_cents > 0 && (
                  <span className="small muted">{fill(C.EXPECTED_N, { amount: dollars(m.head.fixed_expected_cents) })}</span>
                )}
              </div>
              <div className="card sp-fixeds">
                {m.fixed.filter((r) => r.kind === 'fixed').map((r) => <FixedLine key={r.category} r={r} m={m} canEdit={canEdit} />)}
                {m.fixed.some((r) => r.kind === 'commitment') && <p className="sp-fixed-label eyebrow">{C.COMMITMENTS}</p>}
                {m.fixed.filter((r) => r.kind === 'commitment').map((r) => <FixedLine key={r.category} r={r} m={m} canEdit={canEdit} />)}
              </div>
              <p className="small muted">{C.USUAL_NOTE}</p>
            </section>
          )}
          {m.set_aside && m.set_aside.paid.length > 0 && <PaidRows m={m} canEdit={canEdit} />}
          {m.set_aside && m.set_aside.count > 0 && <SetAsideSection m={m} />}
          {m.occasional.length > 0 && (
            <section className="stack" aria-labelledby="sp-once-h">
              <div className="section-head"><h2 id="sp-once-h">{C.PAID_ONCE}</h2><span className="money money--m">{dollars(m.head.occasional_cents)}</span></div>
              <div className="card sp-fixeds">
                {m.occasional.map((r) => (
                  <Link key={r.category} className="sp-fixed is-once" to={`/spending/${r.category}?month=${m.month}`} data-testid="occasional-row">
                    <CalendarClock className="i" size={24} aria-hidden="true" />
                    <span className="sp-fixed__name">{label(r.category)}</span>
                    <span className="sp-fixed__sub">{r.paid_on ? fill(C.PAID_ON, { date: dayLabel(r.paid_on) }) : ''}</span>
                    <span className="money money--m">{dollars(r.spent_cents)}</span>
                    <ChevronRight className="i" size={20} aria-hidden="true" />
                  </Link>
                ))}
              </div>
            </section>
          )}
          {m.income.length > 0 && (
            <section className="stack" aria-labelledby="sp-income-h">
              <div className="section-head"><h2 id="sp-income-h">{C.INCOME}</h2><span className="money money--m money--in strong">{dollars(m.head.income_cents)}</span></div>
              <div className="card sp-fixeds">
                {m.income.map((r) => (
                  <Link key={r.category} className="sp-fixed is-income" to={drillHref(m.month, r.category, m.as_of)} data-testid="income-row">
                    <ArrowDownLeft className="i" size={24} aria-hidden="true" />
                    <span className="sp-fixed__name">{label(r.category)}</span>
                    <span className="sp-fixed__sub" />
                    <span className="money money--m money--in">{dollars(r.cents)}</span>
                    <ChevronRight className="i" size={20} aria-hidden="true" />
                  </Link>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

export default Spending;
