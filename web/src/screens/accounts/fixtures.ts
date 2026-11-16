// Unit-test fixtures for the Accounts tab and one account's page; nothing in the app imports this file.
import type { Account } from '../../api/types';

/** A full Account: `over` sets what the test cares about, the rest is a plain joint checking account. */
export function acct(over: Partial<Account> & Pick<Account, 'id' | 'name'>): Account {
  return {
    type: 'checking', owner: 'joint', source: 'simplefin', institution: 'Big Bank', is_active: true,
    balance_cents: 0, as_of: '2026-10-25', stale_days: 0, ...over,
  };
}

export const ACCTS: Account[] = [
  acct({ id: 1, name: 'Checking ••6789', type: 'checking', source: 'simplefin', balance_cents: 421018, institution: 'Big Bank' }),
  acct({ id: 2, name: 'Rewards Card ••4402', type: 'credit', source: 'simplefin', balance_cents: -118240, institution: 'Big Bank' }),
  acct({ id: 3, name: 'Roth IRA', type: 'roth_ira', source: 'simplefin', balance_cents: 11208000, institution: 'Robo Invest' }),
  acct({ id: 4, name: 'House', type: 'property', source: 'manual', balance_cents: 92000000, institution: 'Manual' }),
];
