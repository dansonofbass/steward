// Unit-test data for the same-account card and sheet; nothing in the app imports this file.
import type { Question } from './api';

export const HELD: Question = {
  id: 'held-7', kind: 'held', name: 'Joint Taxable', bank: 'Betterment', balance_cents: 8421000, candidate_id: 3,
  candidate_name: 'Joint Taxable', candidate_bank: 'Betterment', candidate_balance_cents: 8421000, matches: 23,
  same_balance: true, since: '2026-10-28T13:00:00+00:00',
};
export const PAIR: Question = { ...HELD, id: 'pair-2', kind: 'in_book', matches: 61, same_balance: false, since: '2026-10-28T12:00:00+00:00' };
export const HELD_TEXT = 'Joint Taxable came in again from Betterment through another login. It looks like your Joint Taxable (Betterment · $84,210). Same balance, and 23 of its transactions match.';
export const PAIR_TEXT = 'Joint Taxable and Joint Taxable at Betterment look like the same account: 61 transactions match.';
export const MERGED_TEXT = 'Merged. Joint Taxable now gets updates from both logins; 23 copies were dropped and 2 new transactions kept.';
export const MERGE_REPLY = { merged: { kept: { id: 3, name: 'Joint Taxable' }, dropped: 23, kept_new: 2 }, undo: 'tok' };
