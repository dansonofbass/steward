import { describe, expect, it } from 'vitest';
import { accountKind, INVESTMENT_TYPES, isDayToDay, isInvestment, KIND_ORDER, RETIREMENT_TYPES } from './accountKinds';

describe('accountKind', () => {
  it('sorts accounts the way the Accounts tab groups them (decision 6)', () => {
    expect(accountKind({ type: 'checking', source: 'simplefin' })).toBe('cash');
    expect(accountKind({ type: 'business_checking', source: 'simplefin' })).toBe('cash');
    expect(accountKind({ type: 'credit', source: 'simplefin' })).toBe('credit');
    expect(accountKind({ type: 'mortgage', source: 'simplefin' })).toBe('credit');
    expect(accountKind({ type: 'roth_ira', source: 'simplefin' })).toBe('investments');
    expect(accountKind({ type: 'plan529', source: 'simplefin' })).toBe('investments');
    expect(accountKind({ type: 'unknown', source: 'simplefin' })).toBe('unset');
  });
  it('an account a person updates is Updated manually whatever its type', () => {
    expect(accountKind({ type: 'plan529', source: 'manual' })).toBe('manual');
    expect(accountKind({ type: 'property', source: 'manual' })).toBe('manual');
  });
  it('orders the groups Cash, Credit, Investments, Updated manually, then not set yet', () => {
    expect(KIND_ORDER).toEqual(['cash', 'credit', 'investments', 'manual', 'unset']);
  });
  it('day-to-day is cash and credit by type, the short list Home keeps (decision 7), from a feed or a file (INS-20)', () => {
    expect(isDayToDay({ type: 'checking' })).toBe(true);
    expect(isDayToDay({ type: 'credit' })).toBe(true);
    expect(isDayToDay({ type: 'business_checking' })).toBe(true);
    expect(isDayToDay({ type: 'mortgage' })).toBe(false);
    expect(isDayToDay({ type: 'loan' })).toBe(false);
    expect(isDayToDay({ type: 'roth_ira' })).toBe(false);
    expect(isDayToDay({ type: 'plan529' })).toBe(false);
  });
});

describe('investment types (investment views spec)', () => {
  it('are the six the account page shows its sections for', () => {
    expect([...INVESTMENT_TYPES].sort()).toEqual(['brokerage_taxable', 'hsa', 'k401', 'plan529', 'roth_ira', 'traditional_ira']);
    expect([...RETIREMENT_TYPES].sort()).toEqual(['hsa', 'k401', 'roth_ira', 'traditional_ira']);
    expect(isInvestment('k401')).toBe(true);
    expect(isInvestment('property')).toBe(false);
  });
});
