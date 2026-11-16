import { Info, Landmark, Upload } from 'lucide-react';
import { useAccounts, useSimplefin } from '../../../api/hooks';
import { Link } from '../../../book/links';
import { IMPORT_A_FILE, SIMPLEFIN_90_DAYS } from '../../../lib/copy';
import { dateLabel } from '../../../lib/format';
import { Card } from '../../../ui/Card';
import { Notice } from '../../../ui/Notice';
import { NewAccount, SimplefinCard } from '../../settings/Banks';
import {
  ACCOUNT_ONE, ACCOUNTS_N, ALL_TYPED, IMPORT_LINE, IMPORT_SUB, KEPT_BY_HAND, KEPT_WHY, MANAGE, SIMPLEFIN_LINKED, SIMPLEFIN_NOT_LINKED, SOME_UNTYPED, STEP_HISTORY, STEP_LINK, STEP_TYPES, UNTYPED_WHY,
} from '../copy';
import type { BodyProps, SectionDef } from '../sections';

function LinkStep(_: BodyProps) {
  const simplefin = useSimplefin();
  return (
    <div className="stack">
      {simplefin.data && !simplefin.data.linked && <p className="ob-note"><Info className="i" size={20} aria-hidden="true" /><span>{SIMPLEFIN_90_DAYS}</span></p>}
      <SimplefinCard />
    </div>
  );
}

function TypesStep(_: BodyProps) {
  const accounts = useAccounts();
  if (accounts.error) return <Notice tone="error">{accounts.error.message}</Notice>;
  const untyped = (accounts.data?.accounts ?? []).filter((a) => a.is_active && a.type === 'unknown');
  return (
    <div className="stack">
      <p className="prof-why">{UNTYPED_WHY}</p>
      {untyped.length > 0 && <Card className="lines"><ul className="plain">{untyped.map((a) => <NewAccount key={a.id} account={a} />)}</ul></Card>}
    </div>
  );
}

function HistoryStep(_: BodyProps) {
  return (
    <Card className="lines">
      <div className="line">
        <div className="line__main"><span>{IMPORT_LINE}</span><span className="small muted">{IMPORT_SUB}</span></div>
        <Link className="btn btn--quiet" to="/settings/import"><span className="btn__content"><Upload size={20} aria-hidden="true" /><span>{IMPORT_A_FILE}</span></span></Link>
      </div>
    </Card>
  );
}

/** The card (spec, Banks and accounts): today's summary, every account kept by hand with its last update, and the way
 *  to Settings › Banks and accounts, which keeps reconnect and remove. */
function BanksCard(_: BodyProps) {
  const accounts = useAccounts();
  const list = (accounts.data?.accounts ?? []).filter((a) => a.is_active && a.source === 'manual');
  return (
    <div className="stack">
      <section className="card prof-card__step" aria-labelledby="kept-h">
        <h2 id="kept-h">{KEPT_BY_HAND}</h2>
        <p className="prof-why">{KEPT_WHY}</p>
        <ul className="plain">
          {list.map((a) => <li key={a.id}><Link className="link" to={`/accounts/${a.id}`}>{a.as_of ? `${a.name} · ${dateLabel(a.as_of, new Date())}` : a.name}</Link></li>)}
        </ul>
      </section>
      <Link className="btn btn--quiet" to="/settings/banks"><span className="btn__content"><Landmark size={20} aria-hidden="true" /><span>{MANAGE}</span></span></Link>
    </div>
  );
}

function useBanksSummary(): string[] | null {
  const accounts = useAccounts().data;
  const sf = useSimplefin().data;
  if (!accounts || !sf) return null;
  const active = accounts.accounts.filter((a) => a.is_active);
  const untyped = active.filter((a) => a.type === 'unknown').length;
  return [[sf.linked ? SIMPLEFIN_LINKED : SIMPLEFIN_NOT_LINKED,
    active.length === 1 ? ACCOUNT_ONE : ACCOUNTS_N.replace('{n}', String(active.length)),
    untyped === 0 ? ALL_TYPED : SOME_UNTYPED.replace('{n}', String(untyped))].join(' · ')];
}

export const BANKS_SECTION: SectionDef = {
  icon: Landmark,
  steps: [
    { key: 'link', title: () => STEP_LINK, Body: LinkStep },
    { key: 'types', title: () => STEP_TYPES, Body: TypesStep },
    { key: 'history', title: () => STEP_HISTORY, Body: HistoryStep },
  ],
  Card: BanksCard,
  useSummary: useBanksSummary,
};
