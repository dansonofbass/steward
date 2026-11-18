import { ChevronRight, List, Plus } from 'lucide-react';
import { Suspense, useState, type ComponentType } from 'react';
import { lazyScreen } from '../../lib/lazyScreen';
import { useAccounts, useSimplefin } from '../../api/hooks';
import type { Account } from '../../api/types';
import { useCanEdit } from '../../book/BookContext';
import { Link } from '../../book/links';
import { accountKind, KIND_LABEL, KIND_ORDER, RETIREMENT_TYPES, vehicleLoan, type AccountKind } from '../../lib/accountKinds';
import {
  ACCOUNTS, ACCOUNTS_COUNT, ACCOUNTS_FRESH, ADD_AN_ACCOUNT, ALL_TRANSACTIONS, NO_BALANCE_YET, ONE_ACCOUNT, ONE_ACCOUNT_FRESH,
  LIMITS_UNAVAILABLE, NET_WORTH_SPLIT_UNAVAILABLE, NET_WORTH_TITLE, NET_WORTH_UNAVAILABLE, TODAY_AT, YESTERDAY_AT,
} from '../../lib/copy';
import { dateLabel, localYmd, money } from '../../lib/format';
import { freshness } from '../../lib/freshness';
import { addDays, clockTime, today } from '../../lib/today';
import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { SameAccount } from '../sameaccount/load';
import { AddAccount } from './AddAccount';
import { TaxTreatment } from './TaxTreatment';
import '../../ui/Money.css';
import './accounts.css';

/** The line under the title (decision 6): how many accounts, and when SimpleFIN last brought them up to date —
 *  "today, 6:10 AM", "yesterday, 6:10 AM" or "Oct 23". Without a sync it only counts. */
export function freshLine(accounts: Account[], lastSync: string | null, now: Date): string {
  const n = accounts.length;
  if (!lastSync) return n === 1 ? ONE_ACCOUNT : ACCOUNTS_COUNT.replace('{n}', String(n));
  // The household's day and clock (issue #26), wherever this device is.
  const day = localYmd(lastSync);
  const home = today(now);
  const when = day >= home ? TODAY_AT.replace('{time}', clockTime(lastSync))
    : day === addDays(home, -1) ? YESTERDAY_AT.replace('{time}', clockTime(lastSync))
      : dateLabel(day, home);
  return n === 1 ? ONE_ACCOUNT_FRESH.replace('{when}', when) : ACCOUNTS_FRESH.replace('{n}', String(n)).replace('{when}', when);
}

// Balances are plain, as on Home's account list: a positive one isn't tinted as money coming in.
const plain = (cents: number, cls = '') => <span className={`money money--m${cls}`}>{money(cents)}</span>;

// Each row says when its balance was last updated, under the balance, as Home does (roadmap 11: JR, Oct 26, freshness
// is very useful); a bank feed 3 or more days behind is flagged. A vehicle names its loan instead of its bank.
function Row({ a, today, loan }: { a: Account; today: Date; loan?: Account }) {
  const fresh = freshness(a, today);
  const sub = (loan && vehicleLoan(loan)) ?? a.institution;
  return (
    <Link className="arow" to={`/accounts/${a.id}`}>
      <span className="arow__name">{a.name}</span>
      {a.balance_cents === null ? <span className="arow__bal muted">{NO_BALANCE_YET}</span> : plain(a.balance_cents, ' arow__bal')}
      <span className="arow__sub">{sub}</span>
      {a.balance_cents !== null && <span className={`arow__when${fresh.stale ? ' is-stale' : ''}`} data-testid="account-fresh">{fresh.text}</span>}
      <ChevronRight size={20} aria-hidden="true" />
    </Link>
  );
}

// Updated manually has no total: it would net a house against a car loan (the mockup).
function Kind({ kind, accounts, today, byId }: { kind: AccountKind; accounts: Account[]; today: Date; byId: Map<number, Account> }) {
  const known = accounts.filter((a) => a.balance_cents !== null);
  const total = known.reduce((s, a) => s + (a.balance_cents ?? 0), 0);
  return (
    <section className="card acct-group" aria-labelledby={`kind-${kind}`}>
      <div className="acct-group__head">
        <h2 className="eyebrow" id={`kind-${kind}`}>{KIND_LABEL[kind]}</h2>
        {kind !== 'manual' && known.length > 0 && plain(total)}
      </div>
      {accounts.map((a) => <Row key={a.id} a={a} today={today} loan={a.type === 'vehicle' && a.loan_id ? byId.get(a.loan_id) : undefined} />)}
    </section>
  );
}

function NetWorthMissing() {
  return (
    <section className="acct-sec" aria-labelledby="nw-h">
      <h2 id="nw-h">{NET_WORTH_TITLE}</h2>
      <Notice tone="error"><p>{NET_WORTH_UNAVAILABLE}</p></Notice>
    </section>
  );
}

/** Net worth over time loads in its own small chunk, so this screen (part of the first download) doesn't grow. If the
 *  chunk can't be fetched (a deploy replaced it while the page was open), its section says so and the screen stays. */
export const loadNetWorth = (load: () => Promise<{ default: ComponentType }> = () => import('./NetWorthChart')) =>
  load().catch(() => ({ default: NetWorthMissing }));
const NetWorthChart = lazyScreen(() => loadNetWorth());

function LimitsMissing() {
  return <Notice tone="error"><p>{LIMITS_UNAVAILABLE}</p></Notice>;
}

/** This year's contribution limits load in their own chunk (investment views spec), only when there is a retirement
 *  account; a chunk that can't be fetched leaves a line saying so. */
export const loadLimits = (load: () => Promise<{ default: ComponentType }> = () => import('./invest/LimitsTable')) =>
  load().catch(() => ({ default: LimitsMissing }));
const LimitsTable = lazyScreen(() => loadLimits());

function SplitMissing() {
  return <Notice tone="error"><p>{NET_WORTH_SPLIT_UNAVAILABLE}</p></Notice>;
}

/** Net worth and its split load in their own chunk at the top (investment views spec); a chunk that can't be fetched
 *  leaves a line saying so. */
export const loadSplit = (load: () => Promise<{ default: ComponentType }> = () => import('./NetWorthSplit')) =>
  load().catch(() => ({ default: SplitMissing }));
const NetWorthSplit = lazyScreen(() => loadSplit());

/** The household's Accounts tab: net worth and its split (investment views spec), how fresh it is, All transactions, the accounts by kind, the plan's tax mix, net worth over time and the contribution limits, and Add an account. */
export default function Accounts() {
  const accounts = useAccounts();
  const simplefin = useSimplefin();
  const canEdit = useCanEdit();
  const [adding, setAdding] = useState(false);
  const today = new Date();
  const list = accounts.data?.accounts ?? [];
  const byKind = new Map<AccountKind, Account[]>();
  for (const a of list) {
    const k = accountKind(a);
    byKind.set(k, [...(byKind.get(k) ?? []), a]);
  }

  const byId = new Map(list.map((a) => [a.id, a]));

  return (
    <>
      <div className="screen accounts">
        <header className="accounts__head">
          <h1>{ACCOUNTS}</h1>
          {accounts.isSuccess && !simplefin.isPending && <p className="muted">{freshLine(list, simplefin.data?.last_sync_at ?? null, today)}</p>}
        </header>
        <Suspense fallback={null}><SameAccount /></Suspense>
        {byKind.size > 0 && <Suspense fallback={<Skeleton lines={4} />}><NetWorthSplit /></Suspense>}
        <Link className="card all-row" to="/transactions">
          <List size={24} aria-hidden="true" /><span>{ALL_TRANSACTIONS}</span><ChevronRight size={20} aria-hidden="true" />
        </Link>
        {accounts.isPending && <Card><Skeleton lines={4} /></Card>}
        {accounts.isError && <Notice tone="error">{accounts.error.message}</Notice>}
        {byKind.size > 0 && (
          <div className="acct-groups">
            {KIND_ORDER.filter((k) => byKind.has(k)).map((k) => <Kind key={k} kind={k} accounts={byKind.get(k)!} today={today} byId={byId} />)}
          </div>
        )}
        {byKind.size > 0 && (
          <div className="acct-more">
            <TaxTreatment accounts={list} />
            <Suspense fallback={<Skeleton lines={3} />}><NetWorthChart /></Suspense>
            {list.some((a) => a.is_active && RETIREMENT_TYPES.has(a.type)) && <Suspense fallback={null}><LimitsTable /></Suspense>}
          </div>
        )}
        {canEdit && <Button variant="quiet" icon={Plus} onClick={() => setAdding(true)}>{ADD_AN_ACCOUNT}</Button>}
      </div>
      {adding && <AddAccount onClose={() => setAdding(false)} />}
    </>
  );
}
