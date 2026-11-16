// The Accounts tab's groups (phase 10 decision 6). An account a person updates is "Updated manually" whatever its type;
// a bank account's type picks Cash, Credit or Investments; one with no type yet waits in its own group.
import type { Account, AccountType } from '../api/types';
import { GROUP_CASH, GROUP_CREDIT, GROUP_INVESTMENTS, GROUP_NOT_SET, UPDATED_MANUALLY, VEHICLE_LOAN } from './copy';
import { dollars } from './format';

export type AccountKind = 'cash' | 'credit' | 'investments' | 'manual' | 'unset';
export const KIND_ORDER: AccountKind[] = ['cash', 'credit', 'investments', 'manual', 'unset'];
export const KIND_LABEL: Record<AccountKind, string> = {
  cash: GROUP_CASH, credit: GROUP_CREDIT, investments: GROUP_INVESTMENTS, manual: UPDATED_MANUALLY, unset: GROUP_NOT_SET,
};
const CASH = new Set(['checking', 'savings', 'business_checking']);
const CREDIT = new Set(['credit', 'business_credit', 'mortgage', 'loan']);
const INVESTMENTS = new Set(['brokerage_taxable', 'k401', 'roth_ira', 'traditional_ira', 'hsa', 'plan529', 'property']);

export function accountKind(a: Pick<Account, 'type' | 'source'>): AccountKind {
  if (a.source === 'manual') return 'manual';
  if (CASH.has(a.type)) return 'cash';
  if (CREDIT.has(a.type)) return 'credit';
  if (INVESTMENTS.has(a.type)) return 'investments';
  return 'unset';
}

/** Cash and credit cards: the short list Home keeps (decision 7), by type, however the money comes in (a bank feed, a
 *  file or typed in; install gate INS-20). */
export function isDayToDay(a: Pick<Account, 'type'>): boolean {
  return (CASH.has(a.type) || CREDIT.has(a.type)) && a.type !== 'mortgage' && a.type !== 'loan';
}

/** The investment account page's six types and the four with yearly limits (investment views spec; models.py
 *  INVESTMENT_TYPES and RETIREMENT_TYPES). */
export const INVESTMENT_TYPES: ReadonlySet<AccountType> = new Set<AccountType>(['brokerage_taxable', 'k401', 'roth_ira', 'traditional_ira', 'hsa', 'plan529']);
export const RETIREMENT_TYPES: ReadonlySet<AccountType> = new Set<AccountType>(['k401', 'roth_ira', 'traditional_ira', 'hsa']);
export const isInvestment = (t: AccountType): boolean => INVESTMENT_TYPES.has(t);

/** "car loan $9,800" for a vehicle's loan; null while the loan has no balance (investment views spec). */
export function vehicleLoan(loan: Account): string | null {
  return loan.balance_cents === null ? null : VEHICLE_LOAN.replace('{amount}', dollars(-loan.balance_cents));
}
