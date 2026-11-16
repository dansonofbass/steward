import type { ReimburseChange, SortResult } from '../api/types';
import { label } from './categories';
import {
  ALSO_APPLY_N, ALSO_APPLY_ONE, FACTS_MATCHED, FACTS_MATCHED_ONE, FACTS_ONLY, FACTS_PARTIAL, FACTS_PLAIN, FACTS_REMEMBER,
  NOT_REIMBURSED_FACTS, PARTIAL_REASON, REIMB_FACTS, REIMB_FACTS_LESS, REPAID_FACTS, REPAID_OVER,
} from './copy';
import { money } from './format';

export type Part = { text: string; bold: boolean };

/** A copy string with **bold** runs. Placeholders are filled after the split, so a merchant's name can't add bold. */
export function rich(template: string, vars: Record<string, string | number> = {}): Part[] {
  return template.split('**')
    .map((text, i) => ({ text: text.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m)), bold: i % 2 === 1 }))
    .filter((p) => p.text !== '');
}

export const alsoLine = (n: number) => (n === 1 ? ALSO_APPLY_ONE : ALSO_APPLY_N.replace('{n}', String(n)));

/** What the person chose: the box's count when it was shown (null or 0: no box), and whether it was ticked. */
export type Asked = { matching: number | null; ticked: boolean };

/** The plain facts of a sort, from the reply's result (spec, After: the receipt). The count is the server's `applied`,
 *  never the box's number. */
export function factsOf(sent: string, r: SortResult | undefined, name: string, asked: Asked): Part[] {
  const category = label(r?.category ?? sent);
  const boxShown = (asked.matching ?? 0) > 0;
  if (boxShown && asked.ticked && typeof r?.applied !== 'number') {
    return rich(FACTS_PARTIAL, { category, n: asked.matching ?? 0, reason: PARTIAL_REASON });
  }
  if (r && r.applied > 0) return rich(r.applied === 1 ? FACTS_MATCHED_ONE : FACTS_MATCHED, { category, name, n: r.applied });
  if (r?.rule === 'none') return rich(FACTS_PLAIN, { category, name });
  if (boxShown && !asked.ticked) return rich(FACTS_ONLY, { category });
  return rich(FACTS_REMEMBER, { category, name });
}

/** Reimbursable spec: a repayment's receipt offers Settle when under $100 is left. */
export const SETTLE_OFFER_UNDER_CENTS = 10_000;

/** What the mark, Not reimbursed or a repayment did to the payer's balance (engineering choice 10). The payer's name is
 *  the reimburser record's, from the reply. */
export function reimburseFacts(r: ReimburseChange, category: string, amountCents: number): Part[] {
  const vars = { payer: r.payer, category: label(category), owed: money(r.owed_cents) };
  if (r.change === 'unmarked') return rich(NOT_REIMBURSED_FACTS, { amount: money(Math.abs(amountCents)) });
  if (r.change === 'repaid') {
    return r.owed_cents < 0 ? rich(REPAID_OVER, { ...vars, amount: money(-r.owed_cents) }) : rich(REPAID_FACTS, vars);
  }
  const added = r.owed_cents - r.was_cents;
  return added >= 0 ? rich(REIMB_FACTS, { ...vars, added: money(added) }) : rich(REIMB_FACTS_LESS, { ...vars, less: money(-added) });
}

/** The amount to offer to settle after a repayment that left a little owed; null for anything else. */
export function settleOffer(r: ReimburseChange | null | undefined): number | null {
  return r && r.change === 'repaid' && r.owed_cents > 0 && r.owed_cents < SETTLE_OFFER_UNDER_CENTS ? r.owed_cents : null;
}

/** A repayment brought the balance to exactly $0. */
export const allSquare = (r: ReimburseChange | null | undefined): r is ReimburseChange =>
  !!r && r.change === 'repaid' && r.owed_cents === 0 && r.was_cents !== 0;
