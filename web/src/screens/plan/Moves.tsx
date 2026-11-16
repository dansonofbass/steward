import { Link } from '../../book/links';
import { dollars } from '../../lib/format';
import { sectionPath } from '../../lib/profileSections';
import type { Names, PlanMoves } from './api';
import {
  CHANGE, CHANGE_NAMED, COLLEGE_SHORT, HOW_MOVES, MOVES_A_MONTH, MOVES_A_YEAR, MOVES_COLLEGE, MOVES_HEALTH, MOVES_KID, MOVES_KID_LEVEL,
  MOVES_KIDS, MOVES_KIDS_LEVEL, MOVES_MORTGAGE, MOVES_SAVING, MOVES_SPENDING, MOVES_SS, MOVES_TWO, NOT_ADDED,
} from './copy';

export type MoveRow = { label: string; value: string; to?: string };
const fill = (s: string, v: Record<string, string | number>) => s.replace(/\{(\w+)\}/g, (_, k: string) => String(v[k]));

/** The six rows (P27): Social Security at 67, spending in retirement, the mortgage while it isn't paid off, health
 *  before Medicare, college when there are kids, and saving now (no Change: it is what the accounts show). */
export function moveRows(m: PlanMoves, names: Names): MoveRow[] {
  const { jr_cents: jr, spouse_cents: sp } = m.ss_at_67;
  const ss = jr === null ? NOT_ADDED
    : sp === null ? fill(MOVES_A_MONTH, { amount: dollars(jr) })
      : fill(MOVES_TWO, { jr: names.jr, a: dollars(jr), spouse: names.spouse, b: dollars(sp) });
  const rows: MoveRow[] = [
    { label: MOVES_SS, value: ss, to: sectionPath('benefits', null, 'plan') },
    { label: MOVES_SPENDING, value: fill(MOVES_A_MONTH, { amount: dollars(m.retirement_spending_cents) }), to: '/plan/try' },
  ];
  if (m.mortgage_payoff_year !== null) rows.push({ label: MOVES_MORTGAGE, value: String(m.mortgage_payoff_year), to: sectionPath('home', null, 'plan') });
  rows.push({ label: MOVES_HEALTH, value: fill(MOVES_A_YEAR, { amount: dollars(m.health_premium_cents) }), to: sectionPath('benefits', null, 'plan') });
  const { count, level } = m.college;
  if (count > 0) {
    const value = level === null ? (count === 1 ? MOVES_KID : fill(MOVES_KIDS, { n: count }))
      : count === 1 ? fill(MOVES_KID_LEVEL, { level: COLLEGE_SHORT[level] }) : fill(MOVES_KIDS_LEVEL, { n: count, level: COLLEGE_SHORT[level] });
    rows.push({ label: MOVES_COLLEGE, value, to: sectionPath('kids', null, 'plan') });
  }
  rows.push({ label: MOVES_SAVING, value: fill(MOVES_A_MONTH, { amount: dollars(m.saving_cents) }) });
  return rows;
}

export function Moves({ moves, names, canEdit }: { moves: PlanMoves; names: Names; canEdit: boolean }) {
  return (
    <section className="sec" aria-labelledby="how-moves-h">
      <h2 id="how-moves-h">{HOW_MOVES}</h2>
      <dl className="facts moves">
        {moveRows(moves, names).map((r) => (
          <div key={r.label} className="facts__row">
            <dt>{r.label}</dt>
            <dd>{r.value}{canEdit && r.to && <> <Link className="link moves__change" to={r.to} aria-label={fill(CHANGE_NAMED, { label: r.label })}>{CHANGE}</Link></>}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
