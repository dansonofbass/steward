import { describe, expect, it } from 'vitest';
import fixture from './college_outlook.fixture.json';
import { outlook, roundThousand, type CollegeTable } from './outlook';

const table: CollegeTable = { growth: fixture.growth, levels: fixture.levels };

describe('outlook (the shared fixture)', () => {
  for (const c of fixture.cases) {
    it(c.name, () => {
      expect(outlook(c, fixture.plan_year, table)).toEqual(c.expect);
    });
  }
  it('rounds to the nearest $1,000', () => {
    expect(roundThousand(30_862_555)).toBe(30_900_000);
    expect(roundThousand(149_999)).toBe(100_000);
    expect(roundThousand(150_000)).toBe(200_000);
  });
});
