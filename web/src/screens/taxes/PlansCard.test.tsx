import { fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { stubFetch, wrapBook } from '../../test-utils';
import type { PlansOut } from './api';
import { PlansCard } from './PlansCard';

afterEach(() => vi.unstubAllGlobals());

const point = (label: 'so_far' | 'low' | 'high', text: string, profit: number, solo: number, sep: number) => ({
  label, label_text: text, profit_cents: profit, net_earnings_cents: profit, line: `A Solo 401(k) allows $${(solo - sep) / 100} more at this profit: your own part isn't limited to 20% of earnings.`,
  solo: { own_cents: 2450000, business_cents: sep, catch_up_cents: 0, total_cents: solo, saves_cents: Math.round(solo * 0.3) },
  sep: { total_cents: sep, saves_cents: Math.round(sep * 0.3) } });

const P: PlansOut = {
  available: true, year: 2026, rules_note: '2026 federal and 2025 California rules', never: 'Steward never pays or files anything.',
  default_point: 'low', w2_deferrals_cents: 0, notes: [],
  points: [point('so_far', 'So far', 4000000, 3083700, 743500), point('low', 'Low', 6000000, 3570000, 1120000), point('high', 'High', 10000000, 4308700, 1858700)],
  deadlines: { solo: ['Set up by December 31, 2026', 'Or open a new plan after the year ends, and pay in your own part, by April 15, 2027',
    "Pay in the business's part by April 15, 2027, or October 15, 2027 with an extension"],
    sep: ['Set up and pay in by April 15, 2027, or October 15, 2027 with an extension'] },
};

describe('The Solo 401(k) or SEP card', () => {
  it('opens on the low end and switches profit points', async () => {
    stubFetch({ '/api/taxes/plans': P });
    wrapBook(<PlansCard />);
    expect(await screen.findByRole('heading', { name: 'Solo 401(k) or SEP' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Low' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('Profit at the low end of your range: $60,000')).toBeInTheDocument();
    expect(screen.getByText('$35,700')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'High' }));
    expect(screen.getByText('Profit at the high end of your range: $100,000')).toBeInTheDocument();
    expect(screen.getByText('$43,087')).toBeInTheDocument();
    expect(screen.getByText('Set up and pay in by April 15, 2027, or October 15, 2027 with an extension')).toBeInTheDocument();
    expect(screen.getByText('2026 federal and 2025 California rules')).toBeInTheDocument();
  });
  it('has the plans as columns and short row headers', async () => {
    stubFetch({ '/api/taxes/plans': P });
    const { container } = wrapBook(<PlansCard />);
    await screen.findByRole('heading', { name: 'Solo 401(k) or SEP' });
    const heads = Array.from(container.querySelectorAll('table.tax-table th[scope="col"]')).map((th) => th.textContent);
    expect(heads).toEqual(['', 'Solo 401(k)', 'SEP']);
    const rows = Array.from(container.querySelectorAll('table.tax-table th[scope="row"]')).map((th) => th.textContent);
    expect(rows).toEqual(['Your own part', "The business's part", 'Most in total', 'Lowers 2026 tax by about']);
  });
  it('gives the reason when there is no sole proprietor', async () => {
    stubFetch({ '/api/taxes/plans': { available: false, reason: 'Choose sole proprietor in Settings, Business, to see Solo 401(k) or SEP room.' } });
    wrapBook(<PlansCard />);
    expect(await screen.findByText('Choose sole proprietor in Settings, Business, to see Solo 401(k) or SEP room.')).toBeInTheDocument();
  });
});
