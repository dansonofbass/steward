import { ChevronRight, House } from 'lucide-react';
import { Link } from '../../book/links';
import { dollars, monthYear } from '../../lib/format';
import '../spending/setasides/setasides.css';
import type { PlanInputsOut, PlanOneOff } from './api';
import { BIG_COSTS, BIG_COSTS_INTRO, BIG_COSTS_NOTE, BIG_COST_OVERDUE, BIG_COST_SUB, ESTIMATE_TAG, SETTING_ASIDE_LINK } from './copy';

/** The sub line: the payment year and monthly amount, or, for an overdue one, when it was due and when the plan pays it. */
const sub = (r: PlanOneOff) => (r.overdue
  ? BIG_COST_OVERDUE.replace('{due}', monthYear(r.due_year, r.due_month)).replace('{year}', String(r.year))
  : BIG_COST_SUB.replace('{month}', monthYear(r.due_year, r.due_month)).replace('{monthly}', dollars(r.monthly_cents)));

/** Decision D: the one-offs the engine pays in their year, with a way to Setting aside. Nothing without one. */
export function BigCosts({ inputs }: { inputs: PlanInputsOut }) {
  const rows = inputs.set_asides.one_offs;
  if (rows.length === 0) return null;
  return (
    <section className="sec" aria-labelledby="big-costs-h" data-testid="big-costs">
      <h2 id="big-costs-h">{BIG_COSTS}</h2>
      <p className="sec__intro">{BIG_COSTS_INTRO}</p>
      <div className="card sa-ahead">
        {rows.map((r) => (
          <Link key={r.id} className="sa-ahead__row" to={`/spending/setasides/${r.id}`} data-testid="big-cost-row">
            <House className="i" size={24} aria-hidden="true" />
            <span className="sa-ahead__name">{r.name}</span>
            <span className="sa-ahead__sub">{sub(r)}{r.is_estimate && <span className="tag tag--warn">{ESTIMATE_TAG}</span>}</span>
            <span className="money money--m">{dollars(r.cents)}</span>
          </Link>
        ))}
      </div>
      <p className="small muted">{BIG_COSTS_NOTE} <Link className="link sa-ahead-link" to="/spending/setasides">{SETTING_ASIDE_LINK}<ChevronRight className="i" size={16} aria-hidden="true" /></Link></p>
    </section>
  );
}
