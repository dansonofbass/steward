import { Link } from '../../book/links';
import type { Account } from '../../api/types';
import { isDayToDay } from '../../lib/accountKinds';
import { groupOf } from '../../lib/categories';
import {
  ACCOUNTS, ADD_A_BANK_OR_ACCOUNT, ALL_ACCOUNTS, GROUP_BUSINESS, GROUP_CARDS, GROUP_EVERYDAY, GROUP_HOME, GROUP_INVESTING,
  GROUP_KIDS, GROUP_LOANS, GROUP_OTHER, GROUP_RETIREMENT, GROUP_SAVINGS, GO_TO_ACCOUNTS, HOME_ACCOUNTS_EMPTY, NOTHING_HERE_YET,
  NO_DATA_YET,
} from '../../lib/copy';
import { money } from '../../lib/format';
import { freshness } from '../../lib/freshness';
import { Card } from '../../ui/Card';
import { EmptyState } from '../../ui/EmptyState';
import { Skeleton } from '../../ui/Skeleton';

const ORDER = [GROUP_EVERYDAY, GROUP_CARDS, GROUP_SAVINGS, GROUP_INVESTING, GROUP_RETIREMENT, GROUP_KIDS, GROUP_HOME, GROUP_LOANS, GROUP_BUSINESS, GROUP_OTHER];

function Row({ a, today }: { a: Account; today: Date }) {
  const fresh = freshness(a, today);
  const inner = (
    <>
      <span className="acct__name">{a.name}</span>
      {a.balance_cents === null
        ? <span className="muted acct__bal">{NO_DATA_YET}</span>
        : <span className="money money--m acct__bal">{money(a.balance_cents)}</span>}
      <span className="acct__sub">{a.institution}</span>
      <span className={`acct__when${fresh.stale ? ' stale' : ''}`}>{fresh.text}</span>
    </>
  );
  return <Link className="acct acct--link" data-testid="account-row" to={`/accounts/${a.id}`}>{inner}</Link>;
}

export function AccountGroups({ accounts }: { accounts?: Account[] }) {
  if (!accounts) {
    return (
      <section className="stack" aria-busy="true" aria-label={ACCOUNTS}>
        <div className="groups">{[0, 1, 2].map((i) => <Card key={i}><Skeleton lines={3} /></Card>)}</div>
      </section>
    );
  }
  if (accounts.length === 0) {
    return (
      <section className="card" aria-label={ACCOUNTS}>
        <EmptyState
          title={NOTHING_HERE_YET}
          body={ADD_A_BANK_OR_ACCOUNT}
          action={<Link className="btn btn--primary" to="/accounts"><span className="btn__content">{GO_TO_ACCOUNTS}</span></Link>}
        />
      </section>
    );
  }
  const today = new Date();
  const byGroup = new Map<string, Account[]>();
  for (const a of accounts.filter(isDayToDay)) {
    const g = groupOf(a.type);
    byGroup.set(g, [...(byGroup.get(g) ?? []), a]);
  }
  return (
    <section className="stack" aria-labelledby="accounts-h">
      <h2 id="accounts-h">{ACCOUNTS}</h2>
      {byGroup.size === 0 && <p className="muted">{HOME_ACCOUNTS_EMPTY}</p>}
      <div className="groups">
        {ORDER.filter((g) => byGroup.has(g)).map((g) => {
          const list = byGroup.get(g)!;
          const total = list.reduce((s, a) => s + (a.balance_cents ?? 0), 0);
          const anyData = list.some((a) => a.balance_cents !== null);
          return (
            <Card key={g} className="group">
              <div className="group__head">
                <h3 className="eyebrow">{g}</h3>
                {anyData ? <span className="money money--m">{money(total)}</span> : <span className="muted">{NO_DATA_YET}</span>}
              </div>
              {list.map((a) => <Row key={a.id} a={a} today={today} />)}
            </Card>
          );
        })}
      </div>
      <Link className="link" to="/accounts">{ALL_ACCOUNTS} ›</Link>
    </section>
  );
}
