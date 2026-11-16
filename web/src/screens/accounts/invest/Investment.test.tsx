import { screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useFakeTimers } from '../../../test-clock';
import { stubFetch, wrapBook } from '../../../test-utils';
import { acct } from '../fixtures';
import { PAGE, page } from './fixtures';
import Investment from './Investment';

beforeEach(() => { useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(new Date(2026, 9, 25, 12, 0)); });
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

const taxable = acct({ id: 3, name: 'Taxable', type: 'brokerage_taxable', institution: 'Robo Invest', balance_cents: 18000000 });
const show = (data = PAGE) => { stubFetch({ '/api/accounts/3/investment': data }); wrapBook(<Investment account={taxable} />); };
const byText = (text: string) => (_: string, el: Element | null) => el?.tagName === 'P' && el.textContent === text;

describe("an investment account's page (investment views spec)", () => {
  it('says what the bank sends, then this year, what was put in and market growth', async () => {
    show();
    expect(await screen.findByText('Robo Invest sends: balance, transactions, no holdings')).toBeInTheDocument();
    const figs = screen.getByRole('region', { name: 'This year at a glance' });
    expect(within(figs).getByText('This year')).toBeInTheDocument();
    expect(within(figs).getByText('+$10,000.00')).toBeInTheDocument();
    expect(within(figs).getByText('+5.9% · Since Jan 1')).toBeInTheDocument();
    expect(within(figs).getByText('You put in')).toBeInTheDocument();
    expect(within(figs).getByText('$6,000.00')).toBeInTheDocument();
    expect(within(figs).getByText('Market growth')).toBeInTheDocument();
    expect(within(figs).getByText('+$4,000.00')).toBeInTheDocument();
  });

  it('shows no percent when the start was $0 (Review Focus 4)', async () => {
    show(page({ year: { ...PAGE.year!, start_cents: 0, change_pct: null } }));
    const figs = await screen.findByRole('region', { name: 'This year at a glance' });
    expect(within(figs).getByText('Since Jan 1')).toBeInTheDocument();
    expect(figs.textContent).not.toMatch(/%|NaN|Infinity/);
  });

  it('says from when, and that part is estimated, when it is', async () => {
    show(page({ year: { ...PAGE.year!, from_jan1: false, start: '2026-03-15', estimated: true } }));
    const figs = await screen.findByRole('region', { name: 'This year at a glance' });
    expect(within(figs).getByText('+5.9% · Since Mar 15')).toBeInTheDocument();
    expect(within(figs).getByText('estimated from your pay facts')).toBeInTheDocument();
  });

  it('says when there is no balance from this year', async () => {
    show(page({ year: null }));
    expect(await screen.findByText('No balance from this year yet.')).toBeInTheDocument();
  });

  it('draws the balance against what was put in, since Steward started watching', async () => {
    show();
    const chart = await screen.findByRole('img', { name: /^Balance from \$150,000 in August 2025 to \$180,000 now, with \$8,000 put in\.$/ });
    expect(chart.querySelectorAll('polyline')).toHaveLength(2);
    expect(screen.getByText('Since Aug 2, 2025 (when Steward started watching)')).toBeInTheDocument();
  });

  it('says there is not enough history for a chart with one balance', async () => {
    show(page({ series: [PAGE.series[2]] }));
    expect(await screen.findByText('Not enough history yet.')).toBeInTheDocument();
  });

  it('lists the holdings with the mix, the cost a year, the advisory fee and all in', async () => {
    show();
    const sec = await screen.findByRole('region', { name: "What it's invested in" });
    expect(within(sec).getByText('US stocks 60%')).toBeInTheDocument();
    expect(within(sec).getByText('Other 40%')).toBeInTheDocument();
    const vti = within(sec).getByRole('row', { name: /VTI/ });
    expect(within(vti).getByText('$108,000')).toBeInTheDocument();
    expect(within(vti).getByText('$32')).toBeInTheDocument();
    expect(within(within(sec).getByRole('row', { name: /ACMEX/ })).getByText('cost unknown')).toBeInTheDocument();
    expect(within(sec).getByText('Advisory fee 0.25%: about $450 a year.')).toBeInTheDocument();
    expect(within(sec).getByText(byText('All in, about $482 a year (0.27%).'))).toBeInTheDocument();
    expect(within(sec).getByText('$482 a year').tagName).toBe('STRONG');
    expect(within(sec).getByText('Not counting 1 fund with an unknown cost.')).toBeInTheDocument();
    expect(within(sec).getByText('from Robo Invest, Oct 13')).toBeInTheDocument();
  });

  it('without holdings, says what an import would show', async () => {
    show(page({ holdings: null, all_in: null, advisory: null }));
    const sec = await screen.findByRole('region', { name: "What it's invested in" });
    expect(within(sec).getByText("Import Robo Invest's positions (CSV) to see what it's invested in and what it costs.")).toBeInTheDocument();
  });

  it('an account entered by hand has no "sends" line', async () => {
    show(page({ sends: null, manual: true }));
    await screen.findByRole('region', { name: "What it's invested in" });
    expect(screen.queryByText(/ sends: /)).toBeNull();
  });
});
