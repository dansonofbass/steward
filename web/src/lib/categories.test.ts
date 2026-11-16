import { describe, expect, it } from 'vitest';
import { CATEGORY_GROUPS, CATEGORY_ORDER, CATEGORY_WORDS, findCategories, label } from './categories';

describe('Category groups', () => {
  it('hold every category but Not sorted yet exactly once', () => {
    const grouped = CATEGORY_GROUPS.flatMap((g) => g.keys);
    expect(new Set(grouped).size).toBe(grouped.length);
    expect([...grouped].sort()).toEqual(CATEGORY_ORDER.filter((k) => k !== 'uncategorized').sort());
  });
});

describe('Finding a category by plain words (sorting redesign, decision 6)', () => {
  it('puts Reimbursement in Money in and finds it by its everyday words (reimbursable spec)', () => {
    expect(CATEGORY_GROUPS.find((g) => g.name === 'Money in')!.keys).toContain('reimbursement');
    expect(label('reimbursement')).toBe('Reimbursement');
    for (const q of ['per diem', 'repaid', 'reimb']) expect(findCategories(q)).toEqual(['reimbursement']);
    expect(findCategories('expense')).toEqual(['business_expense', 'reimbursement']);
  });

  it('has at least three everyday words for every category, lowercase', () => {
    for (const k of CATEGORY_ORDER.filter((c) => c !== 'uncategorized')) {
      expect(CATEGORY_WORDS[k]?.length ?? 0, k).toBeGreaterThanOrEqual(3);
      for (const w of CATEGORY_WORDS[k]) expect(w).toBe(w.toLowerCase());
    }
  });

  it('matches the start of a word in the label first, then the everyday words', () => {
    expect(findCategories('gas')).toEqual(['transport', 'utilities']);
    expect(findCategories('uber')).toEqual(['transport']);
    expect(findCategories('parking')).toEqual(['transport']);
    expect(findCategories('vet')).toEqual(['pets']);
    expect(findCategories('EAT')).toEqual(['dining']);
    expect(findCategories('café')).toEqual(['dining']);
    expect(findCategories('interest')).toEqual(['interest', 'fees']);
    expect(findCategories('business inc')).toEqual(['business_income']);
    expect(findCategories('loan')).toEqual(['loan_payments']);
    expect(findCategories('zzz')).toEqual([]);
  });

  it('puts your usual categories first within each tier, then the list order', () => {
    // "car" starts "car wash", "rental car", "car payment", and "card" in "card interest" and "card payment".
    expect(findCategories('car')).toEqual(['transport', 'travel', 'loan_payments', 'fees', 'transfer']);
    expect(findCategories('car', ['loan_payments'])).toEqual(['loan_payments', 'transport', 'travel', 'fees', 'transfer']);
  });

  it('finds Not sorted yet only where it is offered', () => {
    expect(findCategories('not')).toEqual([]);
    expect(findCategories('not', [], true)).toEqual(['uncategorized']);
    expect(findCategories('unsure', [], true)).toEqual(['uncategorized']);
  });
});
