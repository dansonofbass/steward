import { Plus } from 'lucide-react';
import { useSetAsides } from '../../../api/hooks';
import { useCanEdit } from '../../../book/BookContext';
import { Link } from '../../../book/links';
import { TRY_AGAIN } from '../../../lib/copy';
import { dollars } from '../../../lib/format';
import { Button } from '../../../ui/Button';
import { Notice } from '../../../ui/Notice';
import { Skeleton } from '../../../ui/Skeleton';
import { Pills } from '../parts';
import * as C from './copy';
import { CoveredLine } from './Moments';
import { fill, headParts } from './model';
import { SetAsideRowView } from './parts';
import { Suggestions } from './Suggestions';
import { Sep } from '../../../ui/Sep';
import '../spending.css';
import './setasides.css';

export function SetAsides() {
  const q = useSetAsides();
  const canEdit = useCanEdit();
  const back = <Pills on="setasides" />;
  if (q.isError) return <div className="screen spending">{back}<h1>{C.SETTING_ASIDE}</h1><Notice tone="error"><p>{q.error.message}</p><Button variant="quiet" onClick={() => void q.refetch()}>{TRY_AGAIN}</Button></Notice></div>;
  if (!q.data) return <div className="screen spending" aria-busy="true">{back}<h1>{C.SETTING_ASIDE}</h1><Skeleton lines={8} /></div>;
  const l = q.data;

  const parts = headParts(l);

  return (
    <div className="screen spending">
      {back}
      <header className="sp-head">
        <h1>{C.SETTING_ASIDE}</h1>
        <p className="muted">{C.INTRO}</p>
        <div className="sp-total">
          <p className="sp-total__big" data-testid="sa-head">{dollars(l.monthly_cents)} <span className="sp-of">{C.A_MONTH}</span></p>
          <p className="sp-total__line" data-testid="sa-line">
            {parts.map((p, i) => (
              <span key={i} className="sp-total__part">
                <span className={i === parts.length - 1 && l.needs_look > 0 ? 'sp-total__lead' : undefined}>{p}</span>
                {i < parts.length - 1 && <Sep className="sp-total__sep" />}
              </span>
            ))}
          </p>
        </div>
      </header>
      <div className="sa-cols">
        <section className="stack" aria-labelledby="sa-list-h">
          <div className="section-head"><h2 id="sa-list-h">{C.WHAT_IS_SET_ASIDE}</h2><span className="small muted">{C.SOONEST_FIRST}</span></div>
          <CoveredLine rows={l.rows} />
          {l.rows.length === 0 ? <p className="muted">{C.NOTHING_YET}</p>
            : <div className="card sa-rows">{l.rows.map((r) => <SetAsideRowView key={r.id} r={r} asOf={l.as_of} />)}</div>}
          {canEdit && <div className="row-actions"><Link className="link" to="/spending/setasides/new"><Plus className="i" size={20} aria-hidden="true" />{C.ADD}</Link></div>}
          <p className="small muted">{C.LIST_NOTE}</p>
        </section>
        <div className="stack sp-side">
          <Suggestions l={l} canEdit={canEdit} />
          <section className="stack" aria-labelledby="sa-tot-h">
            <div className="section-head"><h2 id="sa-tot-h">{C.TOTALS}</h2></div>
            <div className="card sp-sumcard" data-testid="sa-totals">
              <div className="sp-sumcard__row is-total"><span>{C.EACH_MONTH}</span><span className="money money--m">{dollars(l.monthly_cents)}</span></div>
              <div className="sp-sumcard__row"><span className="muted">{C.YEARLY_TOTAL}</span><span className="money money--m">{dollars(l.yearly_cents)}</span></div>
              <div className="sp-sumcard__row"><span className="muted">{C.ONE_OFF_TOTAL}</span><span className="money money--m">{dollars(l.one_off_cents)}</span></div>
            </div>
            <p className="small muted">{fill(C.TOTALS_NOTE, { amount: dollars(l.monthly_cents) })}</p>
          </section>
        </div>
      </div>
    </div>
  );
}

export default SetAsides;
