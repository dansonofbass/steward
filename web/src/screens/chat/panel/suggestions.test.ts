import { describe, expect, it } from 'vitest';
import { suggestionsFor } from './suggestions';

const TODAY = new Date(2026, 9, 30);

describe('the suggestions (Surfaces › Suggestions)', () => {
  it('accounts by kind', () => {
    expect(suggestionsFor({ kind: 'account', group: 'everyday' }, false, TODAY)).toEqual(['What came in and out this month?', 'How has the balance changed this year?', 'Anything unusual lately?']);
    expect(suggestionsFor({ kind: 'account', group: 'card' }, false, TODAY)).toEqual(['What went on this one this month?', 'How has the balance changed this year?', 'Is the balance going down?']);
    expect(suggestionsFor({ kind: 'account', group: 'invest' }, false, TODAY)).toEqual(['How is this invested?', 'How has it changed this year?', 'How does it compare with our other accounts?']);
  });
  it("a category's first question: over this month, or what made it up", () => {
    expect(suggestionsFor({ kind: 'category', category: 'dining', month: '2026-10', over: true }, false, TODAY))
      .toEqual(['Why is Eating out over this month?', 'Is this higher than usual?', 'Which places did we go to most?']);
    expect(suggestionsFor({ kind: 'category', category: 'dining', month: '2026-10', over: false }, false, TODAY)[0]).toBe('What made up Eating out in October?');
    expect(suggestionsFor({ kind: 'category', category: 'dining', month: '2025-12', over: false }, false, TODAY)[0]).toBe('What made up Eating out in December 2025?');
  });
  it("a viewer's third category question needs no store names", () => {
    expect(suggestionsFor({ kind: 'category', category: 'gifts', month: '2026-10', over: false }, true, TODAY))
      .toEqual(['What made up Gifts in October?', 'Is this higher than usual?', 'How does this compare with last year?']);
  });
  it('a transaction: sorted, or not sorted yet', () => {
    expect(suggestionsFor({ kind: 'transaction', category: 'dining' }, false, TODAY)).toEqual(['Is this a usual amount for Eating out?', 'Does this charge repeat?', 'How much have we spent on Eating out this month?']);
    expect(suggestionsFor({ kind: 'transaction', category: 'uncategorized' }, false, TODAY)).toEqual(['What might this be?', 'Does this charge repeat?', 'Is this a usual amount for us?']);
  });
  it('the Plan, a flag and Care', () => {
    expect(suggestionsFor({ kind: 'plan', page: 'overview' }, false, TODAY)).toEqual(['What would let us retire sooner?', 'How sure is this age?', 'What if we spent 10% less?']);
    expect(suggestionsFor({ kind: 'plan', page: 'how' }, false, TODAY)).toEqual(['What does the plan assume?', 'Why this age and not earlier?', 'What changes the result most?']);
    expect(suggestionsFor({ kind: 'flag' }, false, TODAY)).toEqual(['Why was this flagged?', 'Has this happened before?', 'What should we check?']);
    expect(suggestionsFor({ kind: 'care' }, false, TODAY)).toEqual(['How long does the money last?', 'When might Medi-Cal help?', 'Which scenario lasts longest?']);
    expect(suggestionsFor({ kind: 'care-scenario' }, false, TODAY)).toEqual(['How long does the money last here?', 'When would Medi-Cal apply?', 'What does this cost each month?']);
  });
});
