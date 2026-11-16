import { describe, expect, it } from 'vitest';
import type { Part } from '../../lib/receipt';
import { HELD, HELD_TEXT, MERGED_TEXT, PAIR, PAIR_TEXT } from './fixtures';
import { mergedLine, previewLine, questionLine } from './lines';

const text = (parts: Part[]) => parts.map((p) => p.text).join('');
const bold = (parts: Part[]) => parts.filter((p) => p.bold).map((p) => p.text);
const kept = { id: 3, name: 'Joint Taxable' };

describe("the card's words (same-account spec, Asking and Merging)", () => {
  it("says the spec's line for a held feed, its names in bold", () => {
    expect(text(questionLine(HELD))).toBe(HELD_TEXT);
    expect(bold(questionLine(HELD))).toEqual(['Joint Taxable', 'Betterment', 'Joint Taxable']);
  });

  it('says what it measured: a balance alone, matches alone, or one match', () => {
    expect(text(questionLine({ ...HELD, matches: 0 }))).toMatch(/\(Betterment · \$84,210\)\. Same balance\.$/);
    expect(text(questionLine({ ...HELD, same_balance: false }))).toMatch(/\(Betterment · \$84,210\)\. 23 of its transactions match\.$/);
    expect(text(questionLine({ ...HELD, matches: 1 }))).toMatch(/Same balance, and 1 of its transactions matches\.$/);
  });

  it("says the spec's line for a pair already in the book", () => {
    expect(text(questionLine(PAIR))).toBe(PAIR_TEXT);
    expect(text(questionLine({ ...PAIR, matches: 1 }))).toMatch(/: 1 transaction matches\.$/);
    expect(text(questionLine({ ...PAIR, matches: 0, same_balance: true }))).toMatch(/: they have the same balance\.$/);
  });

  it('says what a merge did, and what Merge into… will do', () => {
    expect(text(mergedLine({ kept, dropped: 23, kept_new: 2 }))).toBe(MERGED_TEXT);
    expect(text(mergedLine({ kept, dropped: 1, kept_new: 0 }))).toBe(
      'Merged. Joint Taxable now gets updates from both logins; 1 copy was dropped and nothing new was kept.');
    expect(previewLine({ kept, dropped: 61, kept_new: 3 })).toBe('61 transactions match and will be dropped; 3 will move over.');
    expect(previewLine({ kept, dropped: 1, kept_new: 1 })).toBe('1 transaction matches and will be dropped; 1 will move over.');
    expect(previewLine({ kept, dropped: 0, kept_new: 0 })).toBe('No transactions match; nothing will move over.');
  });
});
