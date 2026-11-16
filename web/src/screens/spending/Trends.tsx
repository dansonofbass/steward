import { useSearchParams } from 'react-router-dom';
import { useSpendingTrends } from '../../api/hooks';
import type { SpendingTrends, TrendGroup, TrendRow } from '../../api/types';
import { Link } from '../../book/links';
import { label } from '../../lib/categories';
import { TRY_AGAIN } from '../../lib/copy';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import * as C from './copy';
import { fill, monthOnly, overInText, steadyLine, trendSub } from './model';
import { Pills } from './parts';
import { TrendBars } from './TrendBars';
import './spending.css';

function TrendCard({ r, t }: { r: TrendRow; t: SpendingTrends }) {
  const sum = overInText(r);
  return (
    <div className="card sp-trend-card">
      <Link className="sp-trend-row" to={`/spending/${r.category}`} data-testid="trend-card" data-category={r.category}>
        <span className="sp-trend-row__name">{label(r.category)}</span>
        <span className={`sp-trend-row__sum${sum.strong ? ' is-over' : ''}`}>{sum.text}</span>
        <span className="sp-trend-row__sub">{trendSub(r)}</span>
        <TrendBars row={r} months={t.months} current={t.current} />
      </Link>
    </div>
  );
}

export function Trends() {
  const [sp, setSp] = useSearchParams();
  const months = sp.get('months') === '6' ? 6 : 12;
  const q = useSpendingTrends(months);
  const head = (current: string | null) => (
    <header className="sp-head">
      <h1>{C.OVER_TIME_TITLE}</h1>
      {current && <p className="muted">{fill(C.OVER_TIME_INTRO, { month: monthOnly(current) })}</p>}
      <div className="sp-span" role="group" aria-label={C.HOW_FAR_BACK}>
        {([6, 12] as const).map((n) => (
          <button key={n} type="button" aria-pressed={months === n} className={months === n ? 'is-on' : undefined}
            onClick={() => setSp(n === 6 ? { months: '6' } : {}, { replace: true, preventScrollReset: true })}>
            {n === 6 ? C.LAST_6 : C.LAST_12}
          </button>
        ))}
      </div>
    </header>
  );
  const back = <Pills on="trends" />;
  if (q.isError) {
    return <div className="screen spending">{back}{head(null)}<Notice tone="error"><p>{q.error.message}</p><Button variant="quiet" onClick={() => q.refetch()}>{TRY_AGAIN}</Button></Notice></div>;
  }
  if (!q.data) return <div className="screen spending" aria-busy="true">{back}{head(null)}<Skeleton lines={8} /></div>;
  const t = q.data;
  const of = (g: TrendGroup) => t.categories.filter((r) => r.group === g);
  const every = of('everyday');
  const fixed = of('fixed');
  const steady = steadyLine(t.categories);
  const cards = (rows: TrendRow[]) => <div className="sp-trends">{rows.map((r) => <TrendCard key={r.category} r={r} t={t} />)}</div>;
  return (
    <div className="screen spending">
      {back}
      {head(t.current)}
      {every.length + fixed.length === 0 && !steady && <p className="muted">{C.NO_TRENDS}</p>}
      {every.length > 0 && (
        <section className="stack" aria-labelledby="sp-tr-every-h">
          <div className="section-head"><h2 id="sp-tr-every-h">{C.FLEXIBLE}</h2><span className="small muted">{C.BY_TARGET}</span></div>
          {cards(every)}
        </section>
      )}
      {(fixed.length > 0 || steady) && (
        <section className="stack" aria-labelledby="sp-vary-h">
          <div className="section-head"><h2 id="sp-vary-h">{C.FIXED_VARY}</h2></div>
          {fixed.length > 0 && cards(fixed)}
          {steady && <p className="small muted">{steady}</p>}
        </section>
      )}
    </div>
  );
}

export default Trends;
