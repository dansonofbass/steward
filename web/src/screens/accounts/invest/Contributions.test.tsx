import { screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ME, stubFetch, wrapBook } from '../../../test-utils';
import type { InvestmentPage } from './api';
import { ContributionsSection } from './Contributions';
import { LINE } from './fixtures';

vi.mock('../../../celebrate/celebrate', () => ({   // the cheer is Investment.joy.test's; no real chunk here
  burst: vi.fn(), acorn: vi.fn(() => () => {}), winMoment: vi.fn(() => () => {}) }));

beforeEach(() => { stubFetch({ '/api/auth/me': ME }); });
afterEach(() => vi.unstubAllGlobals());

type Data = NonNullable<InvestmentPage['contributions']>;
const DATA: Data = {
  this_year: { you_cents: 1800000, you_from: 'payroll', match_cents: 360000, match_from: 'estimate', rollover_cents: 2000000, out_cents: 0 },
  line: LINE, missing: false,
};

describe('contributions this year (investment views spec, Contributions and limits)', () => {
  it('lists yours with where it came from, the match, a rollover that does not count, and the limit', () => {
    wrapBook(<ContributionsSection data={DATA} />);
    const sec = screen.getByRole('region', { name: 'Contributions this year' });
    expect(within(sec).getByText('Your contributions').nextElementSibling).toHaveTextContent('$18,000 from your pay facts');
    expect(within(sec).getByText('Employer match').nextElementSibling).toHaveTextContent('$3,600 estimated from your pay facts');
    expect(within(sec).getByText('Rollovers in').nextElementSibling).toHaveTextContent('$20,000 Not counted toward the limit.');
    expect(within(sec).getByText('$18,000 of $24,500 (2026 limit)').tagName).toBe('STRONG');
    expect(sec).toHaveTextContent('Raising your contribution 7% for the rest of the year would max it.');
  });

  it('says when it is maxed', () => {
    wrapBook(<ContributionsSection data={{ ...DATA, line: { ...LINE, in_cents: 2450000, maxed: true, short_cents: 0, raise_pct: null } }} />);
    expect(screen.getByText('Maxed for 2026.', { exact: false })).toBeInTheDocument();
  });

  it("says when this year's limits are missing, and shows no limit", () => {
    wrapBook(<ContributionsSection data={{ ...DATA, missing: true, line: { ...LINE, limit_cents: null } }} />);
    expect(screen.getByText("This year's limits aren't in Steward yet.")).toBeInTheDocument();
    expect(screen.queryByText(/of \$24,500/)).toBeNull();
  });

  it('a 401(k) with no limit line (a business plan) shows only what went in', () => {
    wrapBook(<ContributionsSection data={{ ...DATA, this_year: { ...DATA.this_year, rollover_cents: 0 }, line: null }} />);
    expect(screen.getByText('Your contributions')).toBeInTheDocument();
    expect(screen.queryByText(/limit/)).toBeNull();
  });
});
