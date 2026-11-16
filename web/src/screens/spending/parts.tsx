import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { ReactNode } from 'react';
import { ApiError } from '../../api/client';
import { Link } from '../../book/links';
import { TRY_AGAIN } from '../../lib/copy';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { SubNav } from '../../ui/SubNav';
import { monthLong } from '../cashflow/months';
import * as C from './copy';
import { shiftMonth, type Tone } from './model';

export function BackLink({ to, children }: { to: string; children: ReactNode }) {
  return <Link className="link sp-back" to={to}><ChevronLeft className="i" size={20} aria-hidden="true" />{children}</Link>;
}

/** Spending's tabs, at the top of each of its five pages: This month · Over time · Targets · Setting aside · Reimbursements (reimbursable spec; 11b decision 11;
 *  11c decision 6; the polish pass made them tabs under Spending's main tab, so the views no longer read as buttons). */
export function Pills({ on }: { on: 'month' | 'trends' | 'targets' | 'setasides' | 'reimbursements' }) {
  return <SubNav label={C.SPENDING_VIEWS} on={on} items={TABS} />;
}
const TABS = [{ key: 'month', to: '/spending', label: C.THIS_MONTH }, { key: 'trends', to: '/spending/trends', label: C.OVER_TIME },
  { key: 'targets', to: '/spending/targets', label: C.TARGETS }, { key: 'setasides', to: '/spending/setasides', label: C.SETTING_ASIDE },
  { key: 'reimbursements', to: '/spending/reimbursements', label: C.REIMBURSEMENTS }] as const;

/** Decision 7: the track ends at the target, the fill is spent so far, a mark crosses the bar at today. */
export function PaceBar({ fill, tone, today, unsorted = false }: { fill: number; tone: Tone | 'soon' | 'behind'; today: number | null; unsorted?: boolean }) {
  return (
    <span className={`sp-pace__bar${unsorted ? ' sp-pace__bar--unsorted' : ''}`} aria-hidden="true">
      <span className={`sp-pace__fill is-${tone}`} style={{ width: `${fill}%` }} />
      {today !== null && <i className="sp-pace__today" style={{ left: `${today}%` }} />}
    </span>
  );
}

/** Previous stops at `earliest`, the first month with data (ruling 22: the API refuses one before it); next stops at
 *  this month. Both come from the server, never the browser's clock. */
export function MonthSwitcher({ month, earliest, current }: { month: string; earliest: string | null; current: boolean }) {
  const prev = shiftMonth(month, -1);
  const next = shiftMonth(month, 1);
  const left = <ChevronLeft className="i" size={20} aria-hidden="true" />;
  const right = <ChevronRight className="i" size={20} aria-hidden="true" />;
  return (
    <div className="sp-months">
      {earliest !== null && prev >= earliest
        ? <Link className="sp-months__btn" to={`/spending?month=${prev}`} aria-label={monthLong(prev)}>{left}</Link>
        : <button type="button" className="sp-months__btn" disabled aria-label={monthLong(prev)}>{left}</button>}
      <h1>{monthLong(month)}</h1>
      {current
        ? <button type="button" className="sp-months__btn" disabled aria-label={C.NEXT_MONTH}>{right}</button>
        : <Link className="sp-months__btn" to={`/spending?month=${next}`} aria-label={monthLong(next)}>{right}</Link>}
    </div>
  );
}

/** A month the API won't show. Before the book's first month (404, ruling 22) is not an error, just nothing there; a
 *  refused month (422) won't change by asking again; anything else (a 5xx, a 429, a 409) can be tried again. */
export function Refused({ error, month, retry }: { error: Error; month: string | null; retry: () => void }) {
  const status = error instanceof ApiError ? error.status : 0;
  const toThisMonth = month && <Link className="link" to="/spending">{C.THIS_MONTH}</Link>;
  if (status === 404) return <div className="stack"><p>{error.message}</p>{toThisMonth}</div>;
  return (
    <Notice tone="error">
      <p>{error.message}</p>
      {status !== 422 && <Button variant="quiet" onClick={retry}>{TRY_AGAIN}</Button>}
      {toThisMonth}
    </Notice>
  );
}

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;
/** Before the month arrives: the asked-for month's name, or Spending when the server is choosing it. */
export const waitingTitle = (month: string | null) => (month && MONTH.test(month) ? monthLong(month) : C.SPENDING);
