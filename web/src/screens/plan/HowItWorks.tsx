import { useAccounts, useFacts } from '../../api/hooks';
import { useCanEdit } from '../../book/BookContext';
import { Link } from '../../book/links';
import { dateLabel, dollars, localYmd, relativeDays } from '../../lib/format';
import { sectionPath, type SectionKey } from '../../lib/profileSections';
import { untypedCount } from '../../ui/UntypedNotice';
import type { Account } from '../../api/types';
import { useChildren, useEarnings, type EarningsSummary, type Names, type PlanOneOff, type PlanReady, type PlanSetAsides } from './api';
import {
  ESTIMATE_WORD, LU_SET_ASIDES, LU_SET_ASIDES_BY, LU_SET_ASIDES_NO_NAME, NO_ONE_OFFS, ONE_OFF_BULLET, ONE_OFFS_BULLET, ONE_OFFS_IN_PLAN, ONE_OFF_IN_PLAN, YEARLY_BULLET,
  CHILDREN_COUNT, CHILD_ONE, LEFT_OUT_MANY, LEFT_OUT_ONE, MONTHS_COUNT, LU_BALANCES, LU_CHILDREN, LU_EARNINGS, LU_HEALTH, LU_MORTGAGE, LU_PAY, LU_SPENDING, NOT_ADDED, ACCOUNTS_LOADING, ACCOUNTS_UNAVAILABLE,
  HOW_AGES, HOW_AGES_BODY, HOW_HISTORIES, HOW_SOURCES,
} from './copy';
import { Folds, type FoldKey } from './Folds';
import { Moves } from './Moves';
import { peopleFrom } from './people';

export function isStale(note: string): boolean {
  return /last updated \d+ days ago|default mix|^Based on \d+ months/.test(note);
}

export const yearlyBullet = (n: number): string | null => (n > 0 ? YEARLY_BULLET : null);
export function oneOffsBullet(rows: PlanOneOff[]): string | null {
  if (rows.length === 0) return null;
  const list = rows.map((r) => `${r.name}, ${r.year}, ${dollars(r.cents)}${r.is_estimate ? ` ${ESTIMATE_WORD}` : ''}`).join('; ');
  return (rows.length === 1 ? ONE_OFF_BULLET : ONE_OFFS_BULLET).replace('{list}', list);
}

type Row = { label: string; value: string; warn?: boolean; section?: SectionKey; to?: string };
type Args = {
  accounts: Account[] | undefined; accountsFailed?: boolean; factsAsOf: Record<string, string>; earnings: EarningsSummary['records'] | undefined;
  names: Names; childCount: number; spendingMonths: number; today: Date; setAsides: PlanSetAsides;
};

export function lastUpdatedRows(a: Args): Row[] {
  const dates = (a.accounts ?? []).filter((x) => x.is_active && x.as_of).map((x) => x.as_of!).sort();
  const fact = (k: string) => (a.factsAsOf[k] ? dateLabel(a.factsAsOf[k], a.today) : null);
  const rec = (who: string, r: { imported_at: string | null } | null | undefined) =>
    `${who} ${r?.imported_at ? dateLabel(localYmd(r.imported_at), a.today) : NOT_ADDED}`;
  const rows: Row[] = [
    { label: LU_BALANCES, value: a.accounts ? relativeDays(dates.at(-1), a.today) : a.accountsFailed ? ACCOUNTS_UNAVAILABLE : ACCOUNTS_LOADING },
    { label: LU_PAY, value: fact('jr.salary_cents') ?? NOT_ADDED, section: 'you' },
    { label: LU_EARNINGS, value: `${rec(a.names.jr, a.earnings?.jr)} · ${rec(a.names.spouse, a.earnings?.spouse)}`, section: 'benefits' },
    { label: LU_CHILDREN, value: a.childCount === 1 ? CHILD_ONE : CHILDREN_COUNT.replace('{n}', String(a.childCount)), section: 'kids' },
  ];
  if (a.factsAsOf['mortgage.payment_cents']) rows.push({ label: LU_MORTGAGE, value: fact('mortgage.payment_cents')!, section: 'home' });
  rows.push({ label: LU_HEALTH, value: fact('health.premium_cents') ?? NOT_ADDED, section: 'benefits' });
  rows.push({ label: LU_SPENDING, value: MONTHS_COUNT.replace('{n}', String(a.spendingMonths)), warn: a.spendingMonths < 12 });
  const sa = a.setAsides;
  const count = sa.one_offs.length;
  const n = count === 0 ? NO_ONE_OFFS : count === 1 ? ONE_OFF_IN_PLAN : ONE_OFFS_IN_PLAN.replace('{n}', String(count));
  const when = sa.updated_at ? dateLabel(localYmd(sa.updated_at), a.today) : '';
  const value = !sa.updated_at ? NOT_ADDED
    : sa.updated_by ? LU_SET_ASIDES_BY.replace('{date}', when).replace('{name}', sa.updated_by).replace('{n}', n)
      : LU_SET_ASIDES_NO_NAME.replace('{date}', when).replace('{n}', n);
  rows.push({ label: LU_SET_ASIDES, value, to: '/spending/setasides' });
  return rows;
}

/** How it works (polish round item 4): what moves the plan most, with the household's own numbers and a Change link
 *  where one applies; the notices unfolded in amber; every other assumption in five folds that open to the plan's exact
 *  lines; then where the numbers come from and what the ages mean. */
export function HowItWorks({ data }: { data: PlanReady }) {
  const canEdit = useCanEdit();
  const accounts = useAccounts();
  const earnings = useEarnings();
  const kids = useChildren();
  const facts = useFacts();
  const result = data.result;
  const younger = peopleFrom(data.names, facts.data?.facts, result.band[0]?.year ?? new Date().getFullYear(), result.band[0]?.jr_age ?? 40).younger;
  const list = accounts.data?.accounts;
  const untyped = list ? untypedCount(list) : 0;
  const rows = lastUpdatedRows({ accounts: list, accountsFailed: accounts.isError, factsAsOf: data.inputs.facts_as_of, earnings: earnings.data?.records,
    names: data.names, childCount: kids.data?.children.length ?? 0, spendingMonths: data.inputs.spending_months, today: new Date(), setAsides: data.inputs.set_asides });
  const yearly = yearlyBullet(data.inputs.set_asides.yearly_count);
  const oneOffs = oneOffsBullet(data.inputs.set_asides.one_offs);
  const groupOf = (i: number) => result.assumption_groups?.[i] ?? (isStale(result.assumptions[i]) ? 'notice' : 'costs');
  const of = (g: string) => result.assumptions.filter((_, i) => groupOf(i) === g);
  const notices = [...of('notice'), ...(untyped > 0 ? [untyped === 1 ? LEFT_OUT_ONE : LEFT_OUT_MANY.replace('{n}', String(untyped))] : [])];
  const folds: Record<FoldKey, string[]> = {
    markets: [HOW_HISTORIES.replace('{n}', result.histories.toLocaleString('en-US')), ...of('markets')],
    taxes: of('taxes'), ss: of('ss'), lifespans: of('lifespans'),
    costs: [...of('costs'), ...(yearly ? [yearly] : []), ...(oneOffs ? [oneOffs] : [])],
  };
  return (
    <div className="plan how-page">
      {data.inputs.moves && <Moves moves={data.inputs.moves} names={data.names} canEdit={canEdit} />}
      {notices.length > 0 && <ul className="how-list how-notices">{notices.map((n) => <li key={n} className="warn">{n}</li>)}</ul>}
      <Folds folds={folds} />
      <section className="sec" aria-labelledby="how-sources-h">
        <h2 id="how-sources-h">{HOW_SOURCES}</h2>
        <dl className="facts">
          {rows.map((r) => (
            <div key={r.label} className="facts__row">
              <dt>{r.section ? <Link className="link" to={sectionPath(r.section, null, 'plan')}>{r.label}</Link> : r.to ? <Link className="link" to={r.to}>{r.label}</Link> : r.label}</dt>
              <dd className={r.warn ? 'warn' : undefined}>{r.value}</dd>
            </div>
          ))}
        </dl>
      </section>
      <section className="sec" aria-labelledby="how-ages-h">
        <h2 id="how-ages-h">{HOW_AGES}</h2>
        <p>{HOW_AGES_BODY.replace('{younger}', younger)}</p>
      </section>
    </div>
  );
}
