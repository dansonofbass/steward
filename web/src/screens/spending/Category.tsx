import { useQueryClient } from '@tanstack/react-query';
import { ChevronRight, SlidersHorizontal } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { useSpending, useSpendingTrends, useTransactions } from '../../api/hooks';
import { undoToken } from '../../api/profile';
import { aboutFor } from '../../ask/about';
import { saveKind } from '../../api/spending';
import type { EverydayRow, SpendingKind, SpendingMonth, TrendRow, Txn } from '../../api/types';
import { useCanEdit } from '../../book/BookContext';
import { useItemTitle } from '../../frame/itemTitle';
import { Link } from '../../book/links';
import { label } from '../../lib/categories';
import { SHOW_MORE, TRY_AGAIN } from '../../lib/copy';
import { dollars, money } from '../../lib/format';
import { AskAbout } from '../../ui/AskAbout';
import { Button } from '../../ui/Button';
import { Money } from '../../ui/Money';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { TxnName } from '../../ui/TxnName';
import { UndoToast } from '../../ui/UndoToast';
import { monthLong, monthRange, monthShort } from '../cashflow/months';
import { failure } from '../settings/shared';
import * as C from './copy';
import { GivingOutside } from './GivingOutside';
import { KindSelect } from './KindSelect';
import { dayLabel, daysLeftText, fill, fillPct, fixedText, paceTone, SPENDING_KEYS, spareCents, todayPct, trendSub } from './model';
import { BackLink, PaceBar, Refused, waitingTitle } from './parts';
import { TrendBars } from './TrendBars';
import '../transactions.css';
import './spending.css';

/** The head's state line for an everyday category. With no target it only says what is typical: nothing to judge by. */
function everyState(r: EverydayRow, m: SpendingMonth): { word: string; tone: string; rest: string[] } {
  const left = m.current ? [daysLeftText(m.days_left ?? 0)] : [];
  switch (r.state) {
    case 'over': return { word: fill(C.OVER_BY, { amount: dollars(r.over_cents ?? 0) }), tone: r.over_level === 'clear' ? 'is-clear' : '', rest: left };
    case 'none': return { word: C.NO_TARGET, tone: '', rest: r.typical_cents ? [fill(C.TYPICALLY, { amount: dollars(r.typical_cents) })] : [] };
    default: {
      const spare = m.current ? null : spareCents(r);
      return { word: spare !== null ? fill(C.TO_SPARE, { amount: dollars(spare) }) : m.current ? C.ON_TRACK : C.WITHIN, tone: spare !== null ? 'is-spare' : '', rest: left };
    }
  }
}

/** An all-business row or a transfer is out of Spending, even a refund of one; a split counts its personal share,
 *  refund or not; any other refund counts against its category. */
function mark(t: Txn, name: string): string | null {
  if (t.business_pct === 100 || t.is_transfer) return C.NOT_COUNTED;
  if (t.business_pct > 0) return fill(C.YOUR_SHARE, { pct: 100 - t.business_pct });
  if (t.amount_cents > 0) return fill(C.COUNTS_AGAINST, { label: name });
  return null;
}

function TxnDays({ rows, name }: { rows: Txn[]; name: string }) {
  const days: [string, Txn[]][] = [];
  for (const t of rows) {
    const last = days[days.length - 1];
    if (last && last[0] === t.posted_at) last[1].push(t);
    else days.push([t.posted_at, [t]]);
  }
  return (
    <div className="sp-txns">
      {days.map(([day, items]) => (
        <section className="day" key={day}>
          <h3 className="day__head eyebrow">{dayLabel(day)}</h3>
          {items.map((t) => {
            const note = mark(t, name);
            return (
              <div className="txn" key={t.id} data-testid="cat-txn">
                <span className={`txn__name${t.merchant || t.nickname ? '' : ' is-raw'}`}><TxnName t={t} /></span>
                <Money cents={t.amount_cents} sign="auto" />
                <span className="txn__meta"><span>{t.account_name}{note ? ` · ${note}` : ''}</span></span>
              </div>
            );
          })}
        </section>
      ))}
    </div>
  );
}

/** The list failed, which is not the same as nothing being there: the head above still shows what was spent. */
function TxnsFailed({ error, retry }: { error: Error; retry: () => void }) {
  return <Notice tone="error"><p>{error.message}</p><Button variant="quiet" onClick={retry}>{TRY_AGAIN}</Button></Notice>;
}

/** The kind select on a category's page (P12): saves at once, with "Giving is a commitment · Undo". */
function KindPicker({ category, name, kind }: { category: string; name: string; kind: SpendingKind }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ text: string; token: string } | null>(null);
  async function change(k: SpendingKind) {
    if (k === kind || busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = await saveKind(category, k);
      setToast({ text: fill(C.KIND_TOAST, { label: name, kind: C.KIND_NOUN[k] }), token: r.undo });
      await qc.invalidateQueries({ queryKey: ['spending'] });
    } catch (e) {
      setError(failure(e));
    } finally {
      setBusy(false);
    }
  }
  async function undo() {
    const t = toast?.token;
    setToast(null);
    try { if (t) await undoToken(t); } catch (e) { setError(failure(e)); }
    await qc.invalidateQueries({ queryKey: ['spending'] });
  }
  return (
    <div className="sp-cat-kind">
      <KindSelect label={name} value={kind} onChange={(k) => void change(k)} disabled={busy} className="sp-cat-kind__select" />
      {error && <Notice tone="error">{error}</Notice>}
      {toast && <UndoToast text={toast.text} onUndo={() => void undo()} onClose={() => setToast(null)} />}
    </div>
  );
}

function CategoryBody({ category, m, trend, trendMonths, trendCurrent, trendsFailed, back }:
{ category: string; m: SpendingMonth; trend: TrendRow | undefined; trendMonths: string[]; trendCurrent: string; trendsFailed: boolean; back: ReactNode }) {
  const canEdit = useCanEdit();
  const name = label(category);
  const every = m.everyday.find((r) => r.category === category);
  const fixed = m.fixed.find((r) => r.category === category);
  const occ = m.occasional.find((r) => r.category === category);
  const spent = every?.spent_cents ?? fixed?.spent_cents ?? occ?.spent_cents ?? 0;
  const refunds = every?.refunds_cents ?? fixed?.refunds_cents ?? 0;
  const target = every?.target_cents ?? null;
  const range = monthRange(m.month, m.as_of);
  const txns = useTransactions({ category, from: range.from, to: range.to });
  const rows = txns.data?.pages.flatMap((p) => p.transactions) ?? [];
  const nothing = fill(C.NO_SPENDING, { label: name, month: monthLong(m.month) });

  let state: ReactNode = nothing;
  if (every) {
    const s = everyState(every, m);
    state = <><span className={s.tone}>{s.word}</span>{s.rest.length > 0 && <span className="muted">{` · ${s.rest.join(' · ')}`}</span>}</>;
  } else if (fixed) {
    // so_far, under and over already say the usual (or the gap from it), so the line doesn't say it twice.
    const saysUsual = ['so_far', 'under', 'over'].includes(fixed.state);
    const expected = fixed.expected_cents !== null && !saysUsual ? [fill(C.EXPECTED_LINE, { amount: dollars(fixed.expected_cents) })] : [];
    state = <span className={fixed.tone === 'amber' ? 'is-amber' : undefined}>{[...expected, fixedText(fixed)].join(' · ')}</span>;
  } else if (occ) {
    state = <span>{C.ONCE_LINE}</span>;
  }

  // The three months before the one shown; none when it is the oldest drawn or outside the 12.
  const i = trendMonths.indexOf(m.month);
  const from = Math.max(0, i - 3);
  const last3 = trend && i > 0 ? trendMonths.slice(from, i).map((ym, k) => ({ ym, v: trend.spent[from + k] ?? 0 })) : [];
  const sentence = trend ? [
    trend.kind === 'everyday' && trend.target_cents !== null && trend.over_of > 0
      ? (trend.over_in > 0 ? fill(C.OVER_SENTENCE, { n: trend.over_in, m: trend.over_of }) : fill(C.UNDER_SENTENCE, { m: trend.over_of }))
      : null,
    trend.typical_cents ? fill(C.TYPICAL_SENTENCE, { amount: dollars(trend.typical_cents) }) : null,
  ].filter(Boolean).join(' ') : '';

  return (
    <div className="screen spending">
      {back}
      <header className="sp-cat-head">
        <h1 className="eyebrow">{`${name} · ${monthLong(m.month)}`}</h1>
        <AskAbout about={aboutFor.category(category, m.month)} thing={name}
          surface={{ kind: 'category', category, month: m.month, over: m.current && every?.state === 'over' }} />
        {canEdit && m.kinds?.[category] && <KindPicker category={category} name={name} kind={m.kinds[category]} />}
        <p className="sp-cat-head__big" data-testid="cat-total">
          {dollars(spent)}
          {target !== null && <> <span className="sp-of">{fill(C.OF, { amount: dollars(target) })}</span></>}
        </p>
        {every && target !== null && <PaceBar fill={fillPct(spent, target, 0)} tone={paceTone(every, m.current)} today={todayPct(m)} />}
        <p className="sp-cat-head__state" data-testid="cat-state">{state}</p>
        {fixed?.outside_cents !== undefined && <GivingOutside cents={fixed.outside_cents} canEdit={canEdit} />}
        {refunds > 0 && <p className="small muted">{fill(C.REFUND_LINE, { amount: money(refunds), label: name })}</p>}
        {canEdit && (every || fixed) && (
          <div className="row-actions">
            <Link className="link" to="/spending/targets"><SlidersHorizontal className="i" size={20} aria-hidden="true" />{target !== null || fixed ? C.CHANGE_TARGET : C.SET_A_TARGET}</Link>
          </div>
        )}
      </header>
      <div className="sp-cat-cols">
        <div className="stack sp-side">
          {last3.length > 0 && (
            <section className="stack" aria-labelledby="sp-last3-h">
              <div className="section-head"><h2 id="sp-last3-h">{C.LAST_3}</h2></div>
              <div className="sp-last3">
                {last3.map(({ ym, v }) => {
                  const over = target !== null && v > target;
                  return (
                    <div key={ym} data-testid="last3-tile">
                      <span className="eyebrow">{monthShort(ym)}</span>
                      <span className={`money${over ? ' is-over' : ''}`}>{dollars(v)}</span>
                      {target !== null && <span className="small">{over ? fill(C.OVER_SMALL, { amount: dollars(v - target) }) : fill(C.OF, { amount: dollars(target) })}</span>}
                    </div>
                  );
                })}
              </div>
              {sentence && <p className="small muted">{sentence}</p>}
            </section>
          )}
          {trendsFailed && <p className="muted">{C.TRENDS_FAILED}</p>}
          {trend && (
            <section className="stack" aria-labelledby="sp-yr-h">
              <div className="section-head"><h2 id="sp-yr-h">{C.LAST_12_H}</h2><Link className="link" to="/spending/trends">{C.OVER_TIME}<ChevronRight className="i" size={20} aria-hidden="true" /></Link></div>
              <div className="card sp-trend-card">
                <div className="sp-trend-row">
                  <span className="sp-trend-row__sub">{trendSub(trend)}</span>
                  <TrendBars row={trend} months={trendMonths} current={trendCurrent} />
                </div>
              </div>
            </section>
          )}
        </div>
        <section className="stack" aria-labelledby="sp-txn-h">
          <div className="section-head"><h2 id="sp-txn-h">{m.current ? C.THIS_MONTHS_TXNS : fill(C.TXNS_IN, { month: monthLong(m.month) })}</h2></div>
          {txns.isPending ? <Skeleton lines={4} />
            : txns.isError && rows.length === 0 ? <TxnsFailed error={txns.error} retry={() => void txns.refetch()} />
              : rows.length === 0 ? <p className="muted">{nothing}</p> : <TxnDays rows={rows} name={name} />}
          {txns.isFetchNextPageError && rows.length > 0 && <TxnsFailed error={txns.error} retry={() => void txns.fetchNextPage()} />}
          {txns.hasNextPage && !txns.isFetchNextPageError && <Button variant="quiet" busy={txns.isFetchingNextPage} onClick={() => void txns.fetchNextPage()}>{SHOW_MORE}</Button>}
          <Link className="link" to={`/transactions?category=${category}`}>{fill(C.ALL_CAT_TXNS, { label: name })}<ChevronRight className="i" size={20} aria-hidden="true" /></Link>
        </section>
      </div>
    </div>
  );
}

export function Category() {
  const { category = '' } = useParams();
  const [sp] = useSearchParams();
  const month = sp.get('month');
  const known = SPENDING_KEYS.includes(category);
  const q = useSpending(month, known);
  const trends = useSpendingTrends(12, known);
  useItemTitle(known ? label(category) : null);
  const back = <BackLink to={month ? `/spending?month=${month}` : '/spending'}>{C.SPENDING}</BackLink>;
  if (!known) return <div className="screen spending">{back}<h1>{C.SPENDING}</h1><p>{C.UNKNOWN_CATEGORY}</p></div>;
  if (q.isError) return <div className="screen spending">{back}<h1>{waitingTitle(month)}</h1><Refused error={q.error} month={month} retry={() => void q.refetch()} /></div>;
  if (!q.data) return <div className="screen spending" aria-busy="true">{back}<h1>{waitingTitle(month)}</h1><Skeleton lines={6} /></div>;
  return (
    <CategoryBody category={category} m={q.data} trend={trends.data?.categories.find((r) => r.category === category)}
      trendMonths={trends.data?.months ?? []} trendCurrent={trends.data?.current ?? ''} trendsFailed={trends.isError} back={back} />
  );
}

export default Category;
