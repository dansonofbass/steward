import { describe, expect, it } from 'vitest';
import type { ItemRow } from './api';
import { amountText, fill, groupTotal, longDate, longLabel, matches, ordinal, parentName, possessive, updatedLabel } from './format';

const row = (over: Partial<ItemRow>): ItemRow => ({
  id: 1, kind: 'account', name: 'Joint checking', owner: 'joint', owner_label: 'Joint', institution: 'Wells Fargo',
  last4: '4417', status: 'confirmed', data_source: 'feed', type: 'checking', type_label: 'Checking', type_word: 'checking',
  sub: 'Wells Fargo · checking ••4417', amount_cents: 821455, amount_per: null, monthly_cents: null, counts_in_totals: true,
  no_balance: false, total_group: 'cash', updated_on: '2026-10-18', check_reason: null, account_id: 3, ...over,
});

describe('inventory formatting', () => {
  it('fills templates and writes ordinals', () => {
    expect(fill('Edit {name}', { name: 'Homeowners' })).toBe('Edit Homeowners');
    expect([1, 2, 3, 4, 11, 21, 22, 23].map(ordinal)).toEqual(['1st', '2nd', '3rd', '4th', '11th', '21st', '22nd', '23rd']);
  });
  it('shows amounts with their period and no balance as nothing', () => {
    expect(amountText(row({}))).toBe('$8,214.55');
    expect(amountText(row({ kind: 'insurance', amount_cents: 146000, amount_per: 'yr' }))).toBe('$1,460.00 /yr');
    expect(amountText(row({ amount_cents: null, no_balance: true }))).toBeNull();
  });
  it('labels dates and items', () => {
    const today = new Date(2026, 9, 18);
    expect(updatedLabel('2026-10-18', today)).toBe('Today');
    expect(updatedLabel('2026-09-30', today)).toBe('Sep 30');
    expect(longDate('2019-06-12')).toBe('June 12, 2019');
    expect(longLabel('Traditional IRA', 'Fidelity', '3390')).toBe('Fidelity Traditional IRA ••3390');
    expect(longLabel('Citi card', 'Citi', '9012')).toBe('Citi card ••9012');
  });
  it('searches name, bank and last 4', () => {
    expect(matches(row({}), 'wells')).toBe(true);
    expect(matches(row({}), '4417')).toBe(true);
    expect(matches(row({}), 'fidelity')).toBe(false);
    expect(matches(row({}), '  ')).toBe(true);
  });
  it('totals each group the way the list shows it', () => {
    expect(groupTotal('account', [row({}), row({ amount_cents: -118240 }), row({ status: 'closed', amount_cents: 500 })])).toBe('$7,032.15');
    expect(groupTotal('income', [row({ kind: 'income', monthly_cents: 214000 }), row({ kind: 'income', monthly_cents: 138500 })])).toBe('$3,525.00 a month');
    expect(groupTotal('insurance', [row({ kind: 'insurance', monthly_cents: 21200 }), row({ kind: 'insurance', monthly_cents: 18500, counts_in_totals: false })])).toBe('$212.00 a month');
    expect(groupTotal('contact', [row({ kind: 'contact' })])).toBeNull();
  });
  it('a contact reads name, then firm', () => {
    expect(longLabel('Linda Park', 'Park & Reyes Law', null, 'contact')).toBe('Linda Park, Park & Reyes Law');
    expect(longLabel('Traditional IRA', 'Fidelity', '3390')).toBe('Fidelity Traditional IRA ••3390');
  });
  it('names the parent from the first owner label, with no gendered words', () => {
    expect(parentName({ owners: [{ label: 'Margaret' }, { label: 'Joint' }] })).toBe('Margaret');
    expect(parentName({ owners: [{ label: ' Mary Ann Ellis ' }] })).toBe('Mary');
    expect(parentName({ owners: [] })).toBe('this person');
    expect(parentName(null)).toBe('this person');
    expect(possessive('Margaret')).toBe("Margaret's");
    expect(possessive('Venus')).toBe("Venus's");
    expect(fill('Is this one of {names}?', { names: possessive(parentName({ owners: [{ label: 'Margaret' }] })) })).toBe("Is this one of Margaret's?");
  });
});
