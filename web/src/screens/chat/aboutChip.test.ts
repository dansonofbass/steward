import { describe, expect, it } from 'vitest';
import { LEVELS } from '../care/copy';
import type { CheckKey } from '../watching/api';
import { aboutLine, aboutThing, monthWord } from './aboutChip';
import type { AboutWire } from './askApi';
import { CARE_LEVEL_WORDS, CHECK_WORDS } from './copy';

const TODAY = new Date(2026, 9, 30);
const line = (w: AboutWire, labels: Record<string, string> = {}) => aboutLine(w, labels, TODAY);

describe('the chip words (Ask about this, Copy)', () => {
  it('says each kind as the spec does', () => {
    expect(line({ kind: 'account', account: 'Account 3' }, { 'Account 3': 'Checking' })).toBe('About: Checking · sent as Account 3');
    expect(line({ kind: 'category', category: 'dining', month: '2026-10' })).toBe('About: Eating out · October');
    expect(line({ kind: 'plan' })).toBe('About: the Plan');
    expect(line({ kind: 'transaction', date: '2026-10-16', amount_cents: -8072, category: 'uncategorized', account: 'Account 3' }))
      .toBe('About: $80.72 out · Oct 16');
    expect(line({ kind: 'transaction', date: '2026-10-01', amount_cents: 120_000, category: 'income', account: 'Account 1' }))
      .toBe('About: $1,200.00 in · Oct 1');
    expect(line({ kind: 'flag', check: 'large', date: '2026-10-14' })).toBe('About: Large amount flag · Oct 14');
    expect(line({ kind: 'flag', check: 'unusual', date: '2026-10-14' })).toBe('About: Unusual flag · Oct 14');
    expect(line({ kind: 'care' })).toBe('About: Care');
    expect(line({ kind: 'care', scenario: 2, level: 'in_home_help' })).toBe('About: In-home help');
  });
  it('shows the year only when it is not this year, and a transaction never shows its account', () => {
    expect(monthWord('2026-10', TODAY)).toBe('October');
    expect(monthWord('2025-10', TODAY)).toBe('October 2025');
    expect(line({ kind: 'transaction', date: '2025-12-30', amount_cents: -100, category: 'dining', account: 'Account 3' },
      { 'Account 3': 'Alvarez Checking' })).toBe('About: $1.00 out · Dec 30, 2025');
  });
  it('an account with no label yet reads as its alias', () => {
    expect(aboutThing({ kind: 'account', account: 'Account 9' }, {}, TODAY)).toEqual({ thing: 'Account 9', alias: 'Account 9' });
  });
  it("keeps the Care screen's level words and has a word for every watching check", () => {
    expect(CARE_LEVEL_WORDS).toEqual(LEVELS);
    const checks: CheckKey[] = ['scam', 'payee', 'large', 'unusual', 'cash', 'monthly', 'duplicate', 'deposit', 'premium', 'account', 'low'];
    expect(Object.keys(CHECK_WORDS).sort()).toEqual([...checks].sort());
  });
});
