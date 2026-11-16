import { aboutFor } from '../../ask/about';
import { useBook } from '../../book/BookContext';
import { THE_PLAN } from '../../lib/copy';
import { AskAbout } from '../../ui/AskAbout';
import { SubNav } from '../../ui/SubNav';
import { HOW_IT_WORKS, NEXT_DOLLAR_TITLE, OVERVIEW, PLAN_PAGES, TAXES_TAB, TRY_CHANGES } from './copy';

export type PlanTab = 'overview' | 'try' | 'next' | 'how' | 'taxes';

const TABS = [
  { key: 'overview', to: '/plan', label: OVERVIEW },
  { key: 'try', to: '/plan/try', label: TRY_CHANGES },
  { key: 'next', to: '/plan/next', label: NEXT_DOLLAR_TITLE },
  { key: 'how', to: '/plan/how', label: HOW_IT_WORKS },
  { key: 'taxes', to: '/taxes', label: TAXES_TAB },
] as const;
// While setup is unfinished every plan address shows the checklist, so only Overview (where it lives) and Taxes stay.
const UNREADY = TABS.filter((t) => t.key === 'overview' || t.key === 'taxes');

/** The Plan tab's pages in one row (plan subpages decision 1), the same SubNav as Spending's tabs. On Overview and How
 *  it works, with chat on, Ask about the Plan ends the row (Ask about this P18). */
export function PlanTabs({ on, ready = true }: { on: PlanTab; ready?: boolean }) {
  const chat = useBook()?.chat === true;
  const nav = <SubNav label={PLAN_PAGES} on={on} items={ready ? TABS : UNREADY} />;
  if (!chat || !ready || (on !== 'overview' && on !== 'how')) return nav;
  return (
    <div className="plan-tabs-row">
      {nav}
      <AskAbout about={aboutFor.plan()} surface={{ kind: 'plan', page: on }} thing={THE_PLAN} />
    </div>
  );
}

/** Which tab an address under /plan is. */
export function tabOf(pathname: string): PlanTab {
  const m = /\/plan\/(try|next|how)\/?$/.exec(pathname);
  return (m?.[1] as PlanTab | undefined) ?? 'overview';
}
