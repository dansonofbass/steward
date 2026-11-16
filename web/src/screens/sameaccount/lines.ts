import { dollars } from '../../lib/format';
import { rich, type Part } from '../../lib/receipt';
import type { Merged, Question } from './api';
import * as C from './copy';

const count = (n: number, one: string, many: string, none: string) => (n === 0 ? none : n === 1 ? one : many.replace('{n}', String(n)));

/** The question's line (spec, Asking), with what the server measured after it. */
export function questionLine(q: Question): Part[] {
  if (q.kind === 'held') {
    const evidence = q.same_balance
      ? count(q.matches, C.SAME_BALANCE_AND_ONE, C.SAME_BALANCE_AND, C.SAME_BALANCE)
      : count(q.matches, C.ONE_OF_ITS_MATCHES, C.N_OF_ITS_MATCH, '');
    const where = q.candidate_balance_cents === null ? q.candidate_bank : `${q.candidate_bank} · ${dollars(q.candidate_balance_cents)}`;
    return rich(`${C.HELD_LINE} ${evidence}`.trim(), { name: q.name, bank: q.bank, candidate: q.candidate_name, where });
  }
  const evidence = q.matches > 0 ? count(q.matches, C.ONE_MATCHES, C.N_MATCH, '') : C.PAIR_SAME_BALANCE;
  return rich(C.PAIR_LINE, { candidate: q.candidate_name, name: q.name, bank: q.candidate_bank, evidence });
}

/** What a merge did (spec: "Merged. Joint Taxable now gets updates from both logins; …"). */
export const mergedLine = (m: Merged): Part[] => rich(C.MERGED, {
  name: m.kept.name,
  dropped: count(m.dropped, C.DROPPED_ONE, C.DROPPED_N, C.DROPPED_NONE),
  kept: count(m.kept_new, C.KEPT_ONE, C.KEPT_N, C.KEPT_NONE),
});

/** What Merge into… will do (spec: "61 transactions match and will be dropped; 3 will move over"). */
export const previewLine = (m: Merged): string =>
  `${count(m.dropped, C.WILL_DROP_ONE, C.WILL_DROP_N, C.WILL_DROP_NONE)}; ${count(m.kept_new, C.WILL_MOVE_ONE, C.WILL_MOVE_N, C.WILL_MOVE_NONE)}.`;
