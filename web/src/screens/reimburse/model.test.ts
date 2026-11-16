import { describe, expect, it } from 'vitest';
import { ACME } from './fixtures';
import {
  barFill, chargesWord, daysBefore, defaultTripName, detailLine, markTotals, owedLine, reasonText, SETTLE_CATEGORIES, statusWord,
} from './model';

const today = new Date(2026, 9, 28);

describe('the Reimbursements words (reimbursable spec, Where they live)', () => {
  it('says what a payer owes, or has paid beyond what is marked', () => {
    expect(owedLine(ACME)).toBe('Acme owes you $1,240.35');
    expect(owedLine({ ...ACME, owed_cents: -4000 })).toBe("Acme has paid you $40.00 more than you've marked. A charge may not be marked yet.");
  });

  it('the line under it, in whole dollars, and the bar', () => {
    expect(detailLine(ACME, today)).toBe('$2,030 marked since Sep 1 · $790 paid back · last repayment Oct 15');
    expect(detailLine({ ...ACME, since: null, last_repaid_on: null, repaid_cents: 0 }, today)).toBe('$0 paid back');
    expect(barFill(ACME)).toBeCloseTo(79000 / 203000);
    expect([barFill({ ...ACME, marked_cents: 0 }), barFill({ ...ACME, cleared_cents: 999999 })]).toEqual([0, 1]);
  });

  it('statuses, counts, dates, names and the 90 days', () => {
    expect([statusWord('waiting'), statusWord('partly'), statusWord('paid'), statusWord(null)])
      .toEqual(['waiting', 'partly paid back', 'paid back ✓', 'no charges marked yet']);
    expect([chargesWord(1), chargesWord(4)]).toEqual(['1 charge', '4 charges']);
    expect(daysBefore('2026-10-28', 90)).toBe('2026-07-30');
    expect([defaultTripName('Chicago, IL'), defaultTripName(' Denver '), defaultTripName('')]).toEqual(['Chicago trip', 'Denver trip', '']);
  });

  it('Settle picks among spending categories only', () => {
    expect(SETTLE_CATEGORIES).toContain('travel');
    for (const k of ['income', 'interest', 'business_income', 'reimbursement', 'transfer', 'investment', 'uncategorized']) {
      expect(SETTLE_CATEGORIES).not.toContain(k);
    }
  });

  it("a row's reason, and the mark button's count and total", () => {
    expect([reasonText({ why: 'booked' }), reasonText({ why: 'says', place: 'Chicago' }), reasonText({ why: 'regular' }),
      reasonText({ why: 'home_only', category: 'childcare_education' }), reasonText({ why: 'unsure' }), reasonText({ why: 'new' })])
      .toEqual(['booked ahead', 'says Chicago', 'a regular near home', 'Childcare and school', 'no clue either way', 'never seen at home']);
    const rows = [{ id: 1, amount_cents: -42000 }, { id: 2, amount_cents: -2840 }, { id: 3, amount_cents: 4000 }] as Parameters<typeof markTotals>[0];
    expect(markTotals(rows, new Set([1, 3]))).toEqual({ n: 2, total: 38000 });
  });
});
