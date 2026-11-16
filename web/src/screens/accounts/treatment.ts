import type { Account, AccountType } from '../../api/types';

export type TreatRow = { key: string; name: string; cents: number; sub: string };

const COUNTED: { key: string; name: string; types: AccountType[]; tail: string }[] = [
  { key: 'cash', name: 'Cash', types: ['checking', 'savings'], tail: 'spend any time' },
  { key: 'taxable', name: 'Investments', types: ['brokerage_taxable'], tail: 'tax on gains when you sell' },
  { key: 'traditional', name: 'Retirement, taxed later', types: ['k401', 'traditional_ira'], tail: 'taxed as income when you take it out' },
  { key: 'roth', name: 'Retirement, tax-free', types: ['roth_ira'], tail: 'nothing owed when you take it out' },
  { key: 'hsa', name: 'Health savings', types: ['hsa'], tail: 'for health costs, tax-free' },
  { key: 'college', name: 'College savings', types: ['plan529'], tail: 'for school costs' },
];
const OUTSIDE: { key: string; name: string; types: AccountType[]; sub: string }[] = [
  { key: 'home', name: 'Home and mortgage', types: ['property', 'mortgage'], sub: 'Not counted: the plan never sells the house' },
  { key: 'vehicles', name: 'Vehicles', types: ['vehicle'], sub: 'Not counted: the plan never sells them' },
  { key: 'cards', name: 'Cards and loans', types: ['credit', 'loan'], sub: 'Not counted: paid from monthly spending' },
  { key: 'business', name: 'Business', types: ['business_checking', 'business_credit'], sub: 'Not counted' },
];

/** Spec 6 item 5: accounts by how the plan treats them (the engine's buckets, plan_inputs.BUCKET_OF). */
export function treatment(accounts: Account[]) {
  const active = accounts.filter((a) => a.is_active);
  const of = (types: AccountType[]) => active.filter((a) => types.includes(a.type));
  const sum = (list: Account[]) => list.reduce((s, a) => s + (a.balance_cents ?? 0), 0);
  const counted: TreatRow[] = COUNTED.filter((g) => of(g.types).length > 0)
    .map((g) => ({ key: g.key, name: g.name, cents: sum(of(g.types)), sub: `${of(g.types).map((a) => a.name).join(', ')} · ${g.tail}` }));
  const outside: TreatRow[] = OUTSIDE.filter((g) => of(g.types).length > 0)
    .map((g) => ({ key: g.key, name: g.name, cents: sum(of(g.types)), sub: g.sub }));
  const unknown = of(['unknown']);
  return { counted, total: counted.reduce((s, r) => s + r.cents, 0), outside, untyped: { n: unknown.length, cents: sum(unknown) } };
}
