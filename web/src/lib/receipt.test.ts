import { describe, expect, it } from 'vitest';
import type { SortResult } from '../api/types';
import { allSquare, alsoLine, factsOf, reimburseFacts, rich, settleOffer, type Part } from './receipt';

const R = (applied: number, rule: SortResult['rule'] = 'made'): SortResult => ({ category: 'transport', applied, rule, undo: 't' });
const text = (parts: { text: string }[]) => parts.map((p) => p.text).join('');
const bold = (parts: { text: string; bold: boolean }[]) => parts.filter((p) => p.bold).map((p) => p.text);

describe('the facts on a receipt (sorting redesign, After: the receipt)', () => {
  it('bolds the ** runs and fills placeholders after the split, so a name cannot add bold', () => {
    expect(rich('**{category}** for {name}.', { category: 'Gifts', name: 'A **B** C' })).toEqual([
      { text: 'Gifts', bold: true }, { text: ' for A **B** C.', bold: false }]);
  });

  it('says the box for one or many', () => {
    expect(alsoLine(6)).toBe('Also apply to 6 matching transactions');
    expect(alsoLine(1)).toBe('Also apply to 1 matching transaction');
  });

  it('states the matching rows the server changed', () => {
    const p = factsOf('transport', R(6), 'UNION SERVICE CENTER', { matching: 6, ticked: true });
    expect(text(p)).toBe('Getting around for UNION SERVICE CENTER, and for the 6 matching ones. New matching transactions will be categorized automatically.');
    expect(bold(p)).toEqual(['Getting around']);
    expect(text(factsOf('transport', R(1), 'X', { matching: 3, ticked: true }))).toBe('Getting around for X, and for the 1 matching one. New matching transactions will be categorized automatically.');
  });

  it('without matches, unticked, with no rule, and when the reply leaves the count out', () => {
    expect(text(factsOf('transport', R(0), 'UNION SERVICE CENTER', { matching: 0, ticked: true }))).toBe('Getting around for UNION SERVICE CENTER. Steward will remember this for next time.');
    expect(text(factsOf('transport', R(0), 'X', { matching: 6, ticked: false }))).toBe('Getting around for this one only.');
    expect(text(factsOf('fees', { ...R(0, 'none'), category: 'fees' }, '*ABC', { matching: null, ticked: true }))).toBe('Fees for *ABC.');
    expect(text(factsOf('transport', undefined, 'X', { matching: 6, ticked: true }))).toBe("Saved as Getting around. The 6 matching ones weren't changed: Steward's reply didn't include them.");
  });
});

describe('the reimbursable facts (reimbursable spec, Marking and A repayment)', () => {
  const text = (ps: Part[]) => ps.map((p) => p.text).join('');
  const R = { change: 'marked', reimburser_id: 1, payer: 'Acme', was_cents: 82817, owed_cents: 124035 } as const;

  it('says what the mark added and the balance in all, the category in bold', () => {
    const ps = reimburseFacts(R, 'travel', -41218);
    expect(text(ps)).toBe('Travel, reimbursable. Acme owes you $412.18 more ($1,240.35 in all).');
    expect(ps[0]).toEqual({ text: 'Travel', bold: true });
  });

  it('a marked refund lowers the balance', () => {
    expect(text(reimburseFacts({ ...R, was_cents: 40000, owed_cents: 38000 }, 'travel', 2000)))
      .toBe('Travel, reimbursable. Acme owes you $20.00 less ($380.00 in all).');
  });

  it('Not reimbursed says it counts as spending again', () => {
    expect(text(reimburseFacts({ ...R, change: 'unmarked', was_cents: 1840, owed_cents: 0 }, 'transport', -1840)))
      .toBe('Not reimbursed: $18.40 counts as your spending again.');
  });

  it('a repayment says from whom and what is left, both in bold', () => {
    const ps = reimburseFacts({ ...R, change: 'repaid', was_cents: 40000, owed_cents: 6035 }, 'reimbursement', 33965);
    expect(text(ps)).toBe('Reimbursement from Acme. Acme now owes you $60.35.');
    expect(ps.filter((p) => p.bold).map((p) => p.text)).toEqual(['Reimbursement', '$60.35']);
    expect(text(reimburseFacts({ ...R, change: 'repaid', was_cents: 1000, owed_cents: -4000 }, 'reimbursement', 5000)))
      .toBe("Reimbursement from Acme. Acme has paid you $40.00 more than you've marked.");
  });

  it('offers Settle when a repayment leaves under $100, and knows all square', () => {
    const repaid = { ...R, change: 'repaid' as const, was_cents: 40000 };
    expect(settleOffer({ ...repaid, owed_cents: 6035 })).toBe(6035);
    expect([settleOffer({ ...repaid, owed_cents: 10000 }), settleOffer({ ...repaid, owed_cents: 0 }),
      settleOffer({ ...R, owed_cents: 6035 }), settleOffer(null)]).toEqual([null, null, null, null]);
    expect([allSquare({ ...repaid, owed_cents: 0 }), allSquare({ ...repaid, owed_cents: 5 }), allSquare({ ...R, owed_cents: 0 }),
      allSquare(null)]).toEqual([true, false, false, false]);
  });
});
