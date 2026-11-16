import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { wrapBook } from '../../test-utils';
import type { PlanOneOff } from './api';
import { BigCosts } from './BigCosts';
import { planFixture } from './fixtures';

const oneOff = (o: Partial<PlanOneOff> & Pick<PlanOneOff, 'id' | 'name'>): PlanOneOff =>
  ({ year: 2028, due_year: 2028, due_month: 12, overdue: false, cents: 220_000, monthly_cents: 8_500, is_estimate: true, ...o });
const withOneOffs = (one_offs: PlanOneOff[]) => ({ ...planFixture().inputs, set_asides: { updated_at: '2026-10-25T19:00:00+00:00', updated_by: 'JR', yearly_count: 5, one_offs } });

describe('Big costs ahead', () => {
  it('lists each one-off with its year, monthly amount and estimate tag, and links to Setting aside', () => {
    wrapBook(<BigCosts inputs={withOneOffs([oneOff({ id: 6, name: 'Water heater' }), oneOff({ id: 7, name: 'Roof', year: 2032, due_year: 2032, cents: 1_800_000, monthly_cents: 24_300, is_estimate: false })])} />);
    expect(screen.getByRole('heading', { level: 2, name: 'Big costs ahead' })).toBeInTheDocument();
    const rows = screen.getAllByTestId('big-cost-row');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('Water heater');
    expect(rows[0]).toHaveTextContent('Dec 2028 · $85 a month until then');
    expect(rows[0]).toHaveTextContent('Estimate');
    expect(rows[0]).toHaveTextContent('$2,200');
    expect(rows[0]).toHaveAttribute('href', '/b/ours/spending/setasides/6');
    expect(rows[1]).toHaveTextContent('Dec 2032 · $243 a month until then');
    expect(rows[1]).not.toHaveTextContent('Estimate');
    expect(screen.getByText(/^Yearly costs like property tax and car insurance are already in the plan's spending history, so they are not listed here\. Property tax counts there even though it sits under Taxes on Spending\. Only the one-offs are listed, each paid in its year\./)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Setting aside' })).toHaveAttribute('href', '/b/ours/spending/setasides');
  });
  it('shows an overdue one-off as due earlier and planned for the plan year', () => {
    wrapBook(<BigCosts inputs={withOneOffs([oneOff({ id: 8, name: 'Roof', year: 2026, due_year: 2025, due_month: 3, overdue: true, monthly_cents: 0 })])} />);
    const row = screen.getByTestId('big-cost-row');
    expect(row).toHaveTextContent('Roof');
    expect(row).toHaveTextContent('Due Mar 2025, now planned for 2026');
    expect(row).not.toHaveTextContent('a month');
    expect(row).toHaveTextContent('Estimate');
  });
  it('names the real due month', () => {
    wrapBook(<BigCosts inputs={withOneOffs([oneOff({ id: 9, name: 'Fence', year: 2027, due_year: 2027, due_month: 6 })])} />);
    expect(screen.getByTestId('big-cost-row')).toHaveTextContent('Jun 2027 · $85 a month until then');
  });
  it('shows nothing without a one-off', () => {
    wrapBook(<BigCosts inputs={planFixture().inputs} />);
    expect(screen.queryByTestId('big-costs')).toBeNull();
  });
});
