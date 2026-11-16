import { describe, expect, it } from 'vitest';
import fixture from '../college_outlook.fixture.json';
import { consequence } from './consequence';

const table = { growth: fixture.growth, levels: fixture.levels } as never;
const kid = { birth_year: 2023, level: 'private' as const, share_pct: 100, covers_living: true, balance_cents: 1_000_000, monthly_cents: 25_000, real_return: 0.045 };

describe('the consequence line', () => {
  it('rounds to the nearest $1,000 and adds the 529 once one is linked', () => {
    expect(consequence(kid, 'Ava', false, table, 2026)).toBe("About $309,000 in today's dollars for 4 years.");
    expect(consequence(kid, 'Ava', true, table, 2026)).toBe("About $309,000 in today's dollars for 4 years. Ava's 529 is on track to cover about $82,000.");
  });
  it('says all of it, nothing at 0%, and one year in the singular', () => {
    expect(consequence({ ...kid, birth_year: 2012, level: 'in_state_public', share_pct: 30, covers_living: false, balance_cents: 9_000_000, monthly_cents: 0 }, 'Ben', true, table, 2026))
      .toBe("About $15,000 in today's dollars for 4 years. Ben's 529 is on track to cover all of it.");
    expect(consequence({ ...kid, share_pct: 0 }, 'Cy', true, table, 2026)).toBe('Nothing for the Plan to set aside for Cy.');
    expect(consequence({ ...kid, birth_year: 2007, level: 'two_year', balance_cents: 0, monthly_cents: 0 }, 'Dee', false, table, 2026))
      .toBe("About $21,000 in today's dollars for 1 year.");
  });
});
