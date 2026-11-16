import { dateLabel, money } from '../../../lib/format';
import type { YearFigures } from './api';
import { ESTIMATED, FIGURES_LABEL, MARKET_GROWTH, NO_YEAR, SINCE_DAY, SINCE_JAN1, THIS_YEAR, YOU_PUT_IN } from './copy';
import { pctText } from './format';

/** This year's three figures (investment views spec): the change with its percent, what was put in, and market growth,
 *  the change less what was put in. The window starts on Jan 1, or at the first balance when that is later. */
export function Figures({ year, today = new Date() }: { year: YearFigures | null; today?: Date }) {
  if (!year) return <p className="muted inv-none">{NO_YEAR}</p>;
  const since = year.from_jan1 ? SINCE_JAN1 : SINCE_DAY.replace('{date}', dateLabel(year.start, today));
  return (
    <section className="inv-figs" aria-label={FIGURES_LABEL}>
      <div className="card inv-fig">
        <span className="inv-fig__label">{THIS_YEAR}</span>
        <span className="money money--l">{money(year.change_cents, { sign: 'always' })}</span>
        <span className="inv-fig__sub">{year.change_pct !== null ? `${pctText(year.change_pct)} · ${since}` : since}</span>
      </div>
      <div className="card inv-fig">
        <span className="inv-fig__label">{YOU_PUT_IN}</span>
        <span className="money money--l">{money(year.put_in_cents)}</span>
        {year.estimated && <span className="inv-fig__sub">{ESTIMATED}</span>}
      </div>
      <div className="card inv-fig">
        <span className="inv-fig__label">{MARKET_GROWTH}</span>
        <span className="money money--l">{money(year.growth_cents, { sign: 'always' })}</span>
      </div>
    </section>
  );
}
