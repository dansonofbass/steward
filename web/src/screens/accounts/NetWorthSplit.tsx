import { useEffect, useRef, useState } from 'react';
import { useAccounts, useSummary } from '../../api/hooks';
import type { Account, SplitKey } from '../../api/types';
import { Link } from '../../book/links';
import { vehicleLoan } from '../../lib/accountKinds';
import { withCelebrate } from '../../lib/celebrations';
import { dollars, money } from '../../lib/format';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { crossedMilestone } from './joy';
import { DOWN_THIS_YEAR, LINE_LABELS, MILESTONE_CHEER, NET_WORTH, UP_THIS_YEAR, VEHICLE_LINE } from './splitCopy';
import './split.css';

const ORDER: SplitKey[] = ['investable', 'home_and_cars', 'owed', 'business', 'unset'];
const ALWAYS = new Set<SplitKey>(['investable', 'home_and_cars', 'owed']);

/** "Subaru · car loan $9,800" for a vehicle with its loan; otherwise the account's name. */
export function accountLine(a: Account, byId: Map<number, Account>): string {
  const loan = a.type === 'vehicle' && a.loan_id ? byId.get(a.loan_id) : undefined;
  const text = loan ? vehicleLoan(loan) : null;
  return text === null ? a.name : VEHICLE_LINE.replace('{name}', a.name).replace('{loan}', text);
}

/** Net worth at the top of Accounts (investment views spec): the figure, its change this year, and Investable, Home and
 *  cars and What you owe, each opening its accounts; Business and Type not set yet only when they have any, so the
 *  lines always add up. In its own chunk, so Accounts (part of the first download) doesn't grow. */
export default function NetWorthSplit() {
  const s = useSummary();
  const accounts = useAccounts();
  const ref = useRef<HTMLElement>(null);
  const [cheer, setCheer] = useState<string | null>(null);
  const worth = s.data?.net_worth_cents;
  useEffect(() => {
    if (worth === undefined) return;
    const m = crossedMilestone(worth);
    if (m === null) return;
    setCheer(MILESTONE_CHEER.replace('{amount}', dollars(m)));
    const el = ref.current;
    if (el) void withCelebrate((c) => { c.burst({ over: el }); });
  }, [worth]);
  if (s.isPending) return <Skeleton lines={4} />;
  if (s.isError) return <Notice tone="error"><p>{s.error.message}</p></Notice>;
  const { split, net_worth_cents: total, change_year_cents: change } = s.data;
  const byId = new Map((accounts.data?.accounts ?? []).map((a) => [a.id, a]));
  return (
    <section className="nws" aria-labelledby="nws-h" ref={ref}>
      <h2 id="nws-h" className="eyebrow">{NET_WORTH}</h2>
      <span className="money money--xl nws__total" data-testid="nws-total">{money(total)}</span>
      {change !== null && <p className="nws__change">{(change >= 0 ? UP_THIS_YEAR : DOWN_THIS_YEAR).replace('{amount}', dollars(Math.abs(change)))}</p>}
      {cheer && <p className="nws__cheer">{cheer}</p>}
      <div className="nws__lines">
        {ORDER.filter((k) => ALWAYS.has(k) || split[k].account_ids.length > 0).map((k) => (
          <details key={k} className="nws__line">
            <summary><span className="nws__name">{LINE_LABELS[k]}</span><span className="money nws__amount" data-testid="nws-line">{money(split[k].cents)}</span></summary>
            <ul className="nws__accts">
              {split[k].account_ids.map((id) => {
                const a = byId.get(id);
                return a ? <li key={id}><Link to={`/accounts/${id}`}>{accountLine(a, byId)}</Link><span className="money">{money(a.balance_cents ?? 0)}</span></li> : null;
              })}
            </ul>
          </details>
        ))}
      </div>
    </section>
  );
}
