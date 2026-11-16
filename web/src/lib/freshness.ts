import type { Account } from '../api/types';
import { DAYS_OLD, LAST_UPDATED } from './copy';
import { relativeDays } from './format';

/** A bank feed should be no more than a couple of days behind; at 3 days its balance is flagged (Home's rule). */
export const STALE_DAYS = 3;

/** When an account's balance was last updated, and whether that's old enough to flag. Home and the Accounts tab say it
 *  the same way. An account kept by hand is never flagged: it is meant to change only when someone updates it. */
export function freshness(a: Pick<Account, 'as_of' | 'stale_days' | 'source'>, today: Date): { text: string; stale: boolean } {
  const stale = a.source !== 'manual' && a.stale_days !== null && a.stale_days >= STALE_DAYS;
  if (stale) return { text: DAYS_OLD.replace('{n}', String(a.stale_days)), stale };
  return { text: a.as_of === null ? relativeDays(null, today) : LAST_UPDATED.replace('{when}', relativeDays(a.as_of, today)), stale };
}
