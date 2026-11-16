import { ChevronLeft, GitMerge } from 'lucide-react';
import { Suspense, useState, type ComponentType } from 'react';
import { lazyScreen } from '../../lib/lazyScreen';
import { useParams } from 'react-router-dom';
import { useAccounts } from '../../api/hooks';
import type { Account, AccountType } from '../../api/types';
import { aboutFor, type Surface } from '../../ask/about';
import { useBook, useCanEdit } from '../../book/BookContext';
import { Link, Navigate, useNavigate } from '../../book/links';
import { isInvestment } from '../../lib/accountKinds';
import {
  ACCOUNTS, ENTERED_BY_HAND, INVESTMENT_UNAVAILABLE, LAST_UPDATED, MERGE_INTO, NO_BALANCE_YET, TRY_AGAIN, UPDATE,
  UPDATED_MANUALLY,
} from '../../lib/copy';
import { dateLabel, money, relativeDays } from '../../lib/format';
import { AskAbout } from '../../ui/AskAbout';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import Transactions from '../Transactions';
import { ownerOptions } from '../settings/shared';
import type { MergeReply } from '../sameaccount/api';
import { MergedNote, MergeInto } from '../sameaccount/load';
import { BalanceSheet } from './ManualAccounts';
import '../../ui/Money.css';
import './accounts.css';

// Under the name: a bank's account names its bank and when it was last updated; one updated manually says so, with the
// date of its balance.
function freshness(a: Account, today: Date): string {
  if (a.source === 'manual') return [UPDATED_MANUALLY, a.as_of && dateLabel(a.as_of, today)].filter(Boolean).join(' · ');
  return [a.institution, a.as_of && LAST_UPDATED.replace('{when}', relativeDays(a.as_of, today))].filter(Boolean).join(' · ');
}

/** An investment account's line (investment views spec, Head): its bank or "Entered by hand", how fresh, and the owner. */
export function investFreshness(a: Account, today: Date, owner: string | undefined): string {
  const first = a.source === 'manual'
    ? [ENTERED_BY_HAND, a.as_of && dateLabel(a.as_of, today)].filter(Boolean).join(' · ')
    : freshness(a, today);
  return [first, owner].filter(Boolean).join(' · ');
}

type InvestmentProps = { account: Account };
function InvestmentMissing(_props: InvestmentProps) {
  return <Notice tone="error"><p>{INVESTMENT_UNAVAILABLE}</p></Notice>;
}

/** The investment sections load in their own chunk, so this page (part of the first download) doesn't grow. If the
 *  chunk can't be fetched (a deploy replaced it while the page was open), a line says so and the page stays. */
export const loadInvestment = (load: () => Promise<{ default: ComponentType<InvestmentProps> }> = () => import('./invest/Investment')) =>
  load().catch(() => ({ default: InvestmentMissing }));
const Investment = lazyScreen(() => loadInvestment());

const back = <Link className="link back" to="/accounts"><ChevronLeft className="i" size={20} aria-hidden="true" />{ACCOUNTS}</Link>;

// Ask about this (Engineering choice 6): which three suggestions an account gets.
const CARD_TYPES = new Set<AccountType>(['credit', 'business_credit', 'mortgage', 'loan']);
const askGroup = (t: AccountType): Extract<Surface, { kind: 'account' }>['group'] =>
  CARD_TYPES.has(t) ? 'card' : isInvestment(t) || t === 'property' || t === 'vehicle' ? 'invest' : 'everyday';

/** One account (engineering choice 2): ‹ Accounts, its name, balance and freshness, then its transactions with the
 *  same filters as All transactions, kept in the address so Back returns to them. One updated manually lists its
 *  transactions too: a file can be imported into it. An investment account adds its owner, Update for one entered by
 *  hand, and its sections between the head and the transactions (investment views spec). A manager sees Merge into… on
 *  a bank's account that has another of its type (same-account spec); after a merge the kept account's page says what
 *  happened, with Undo. An id the book doesn't have opens Accounts. */
export default function AccountPage() {
  const { id = '' } = useParams();
  const accounts = useAccounts();
  const book = useBook();
  const canEdit = useCanEdit();
  const navigate = useNavigate();
  const [updating, setUpdating] = useState(false);
  const [merging, setMerging] = useState(false);
  const [merged, setMerged] = useState<MergeReply | null>(null);
  // The same loading and error states as an inventory item's page; the error keeps ‹ Accounts as a way out.
  // The class `transactions` gives the error the same column and spacing as the page with its transactions.
  if (accounts.isPending) return <div className="screen" aria-busy="true"><Skeleton lines={8} /></div>;
  if (accounts.isError) {
    return (
      <div className="screen transactions">
        {back}
        <Notice tone="error"><p>{accounts.error.message}</p><Button variant="quiet" onClick={() => accounts.refetch()}>{TRY_AGAIN}</Button></Notice>
      </div>
    );
  }
  const a = accounts.data.accounts.find((x) => String(x.id) === id);
  if (!a) return <Navigate to="/accounts" replace />;
  const today = new Date();
  const invest = isInvestment(a.type);
  const owner = ownerOptions(book?.owners, a.owner).find((o) => o.value === a.owner)?.label;
  // Of its type; one whose type isn't set yet (a newer duplicate, often) can go into any: the kept one's type stands.
  const others = accounts.data.accounts.filter((x) => x.id !== a.id && x.is_active && x.source === 'simplefin'
    && (a.type === 'unknown' || x.type === a.type));
  const canMerge = canEdit && a.source === 'simplefin' && a.is_active && others.length > 0;

  // The balance is plain, as on the Accounts tab and Home: a positive one isn't tinted as money coming in.
  const head = (
    <>
      {back}
      <header className="acct-head">
        <h1>{a.name}</h1>
        {a.balance_cents === null ? <p className="muted">{NO_BALANCE_YET}</p> : <span className="money money--xl">{money(a.balance_cents)}</span>}
        <p className="acct-head__sub">
          <span>{invest ? investFreshness(a, today, owner) : freshness(a, today)}</span>
          {invest && canEdit && a.source === 'manual' && <> · <button type="button" className="link" onClick={() => setUpdating(true)}>{UPDATE}</button></>}
        </p>
        {(canMerge || book?.chat === true) && (
          <span className="acct-head__acts">
            <AskAbout about={aboutFor.account(a)} surface={{ kind: 'account', group: askGroup(a.type) }} thing={a.name} />
            {canMerge && <Button variant="quiet" icon={GitMerge} onClick={() => { setMerging(true); }}>{MERGE_INTO}</Button>}
          </span>
        )}
      </header>
      {merged && merged.merged.kept.id === a.id && <Suspense fallback={null}><MergedNote key={merged.undo} reply={merged} /></Suspense>}
      {invest && <Suspense fallback={<Skeleton lines={6} />}><Investment account={a} /></Suspense>}
      {merging && (
        <Suspense fallback={null}>
          <MergeInto account={a} others={others} onClose={() => { setMerging(false); }}
            onMerged={(r) => { setMerging(false); setMerged(r); navigate(`/accounts/${r.merged.kept.id}`); }} />
        </Suspense>
      )}
    </>
  );
  return (
    <>
      <Transactions key={a.id} accountId={a.id} head={head} />
      {updating && <BalanceSheet account={a} onClose={() => setUpdating(false)} onSaved={() => setUpdating(false)} />}
    </>
  );
}
