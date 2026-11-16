import { describe, expect, it } from 'vitest';
import { LINE, PAGE } from './fixtures';
import { bpText, limitAmount, limitSentence, pctText, previewLine, sendsLine, sourceLine } from './format';

describe('the investment page words', () => {
  it('says what a bank sends (investment views spec, What the bank sends)', () => {
    expect(sendsLine('Betterment', { holdings: false, transactions: true })).toBe('Betterment sends: balance, transactions, no holdings');
    expect(sendsLine('Workplace', { holdings: true, transactions: false })).toBe('Workplace sends: balance, no transactions, holdings');
  });
  it('writes a change as a signed percent and a fee as a plain one', () => {
    expect([pctText(5.9), pctText(-2), pctText(0)]).toEqual(['+5.9%', '−2.0%', '0.0%']);
    expect([bpText(25), bpText(100), bpText(5), bpText(30)]).toEqual(['0.25', '1', '0.05', '0.3']);
  });
  it('names where the holdings came from', () => {
    const today = new Date(2026, 9, 25);
    expect(sourceLine(PAGE.holdings!, 'Robo Invest', today)).toBe('from Robo Invest, Oct 13');
    expect(sourceLine({ ...PAGE.holdings!, source: 'import', filename: 'betterment.csv' }, 'Betterment', today)).toBe("from betterment.csv's import, Oct 13");
    expect(sourceLine({ ...PAGE.holdings!, source: 'statement', statement_month: 'Mar 2026' }, 'Robo', today)).toBe('from Statement, Mar 2026 (PDF)');
  });
});

describe('the preview line (investment views spec, Rows that don\'t count)', () => {
  it('sums the file against the balance as the spec writes it, or says the difference', () => {
    expect(previewLine({ count: 12, total_cents: 8421000, balance_cents: 8421000, difference_cents: 0 })).toBe('12 positions · $84,210; your balance is $84,210');
    expect(previewLine({ count: 12, total_cents: 8421000, balance_cents: 8450000, difference_cents: -29000 }))
      .toBe('12 positions · $84,210; your balance is $84,500, a difference of $290.');
    expect(previewLine({ count: 3, total_cents: 8421050, balance_cents: 8421000, difference_cents: 50 })).toBe('3 positions · $84,211; your balance is $84,210');
    expect(previewLine({ count: 1, total_cents: 100, balance_cents: null, difference_cents: null })).toBe('1 position · $1');
  });
});

describe('the limit line (investment views spec, "On pace")', () => {
  it('says how far short the pace falls, and the raise that would max it', () => {
    expect(limitSentence(LINE)).toBe('On pace for $21,800 by Dec 31: $2,700 short of the limit. Raising your contribution 7% for the rest of the year would max it.');
    expect(limitSentence({ ...LINE, raise_pct: null })).toBe('On pace for $21,800 by Dec 31: $2,700 short of the limit.');
    expect(limitAmount(LINE)).toBe('$18,000 of $24,500 (2026 limit)');
  });
  it('says when it is maxed, on pace to max, or when the limits are missing', () => {
    expect(limitSentence({ ...LINE, maxed: true, short_cents: 0, raise_pct: null })).toBe('Maxed for 2026.');
    expect(limitSentence({ ...LINE, short_cents: 0, raise_pct: null })).toBe('On pace to max it by Dec 31.');
    expect(limitSentence({ ...LINE, limit_cents: null })).toBe("This year's limits aren't in Steward yet.");
  });
});
