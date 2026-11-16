import { screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { reply, stubFetch, wrap } from '../../../test-utils';
import { LINE } from './fixtures';
import LimitsTable from './LimitsTable';

vi.mock('../../../celebrate/celebrate', () => ({   // the cheer is Investment.joy.test's; no real chunk here
  burst: vi.fn(), acorn: vi.fn(() => () => {}), winMoment: vi.fn(() => () => {}) }));

afterEach(() => vi.unstubAllGlobals());

describe('the limits table on Accounts (investment views spec)', () => {
  it("shows each person's limits once, with the household's HSA", async () => {
    stubFetch({ '/api/contributions': { year: 2026, missing: false, lines: [LINE, { ...LINE, kind: 'hsa', owner: 'household', name: '', label: 'HSA', in_cents: 875000, limit_cents: 875000, maxed: true, short_cents: 0, raise_pct: null }] } });
    wrap(<LimitsTable />);
    const sec = await screen.findByRole('region', { name: 'Contribution limits for 2026' });
    expect(within(sec).getByText('401(k) · JR')).toBeInTheDocument();
    expect(within(sec).getByText('$18,000 of $24,500 (2026 limit)')).toBeInTheDocument();
    expect(within(sec).getByText('HSA')).toBeInTheDocument();
    expect(within(sec).getByText('Maxed for 2026.')).toBeInTheDocument();
  });

  it('says when the limits are missing, and still shows what went in', async () => {
    stubFetch({ '/api/contributions': { year: 2027, missing: true, lines: [{ ...LINE, year: 2027, limit_cents: null }] } });
    wrap(<LimitsTable />);
    expect(await screen.findByText("This year's limits aren't in Steward yet.")).toBeInTheDocument();
    expect(screen.getByText('$18,000')).toBeInTheDocument();
  });

  it('shows nothing when there is no line', async () => {
    let answered = false;
    stubFetch({ '/api/contributions': () => { answered = true; return reply({ year: 2026, missing: false, lines: [] }); } });
    const { container } = wrap(<LimitsTable />);
    await waitFor(() => expect(answered).toBe(true));
    await waitFor(() => expect(container.textContent).toBe(''));
    expect(screen.queryByRole('region')).toBeNull();
  });
});
