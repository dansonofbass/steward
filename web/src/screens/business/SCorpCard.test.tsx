import { screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { stubFetch, wrapBook } from '../../test-utils';
import { SCorpCard } from './SCorpCard';

afterEach(() => vi.unstubAllGlobals());

describe('The S-corp card', () => {
  it('says what an S-corp would save at the range, with the numbers', async () => {
    stubFetch({ '/api/business/s-corp': { available: true, year: 2026, line: 'An S-corp would save about $3,700 a year at your profit.', worth_it: true, salary_pct: 50, cost_cents: 150000, rules_note: '2026 tax rules',
      state_note: "Includes California's S-corp franchise tax, employer unemployment and training taxes, and SDI on the salary.",
      points: [{ label: 'middle', profit_cents: 8000000, salary_cents: 4000000, sole_tax_cents: 1930400, scorp_tax_cents: 1412000, cost_cents: 150000, saves_cents: 368400, payroll_cents: 612000, franchise_cents: 80000, sdi_cents: 52000, unemployment_cents: 24500 }] } });
    wrapBook(<SCorpCard year={2026} />);
    expect(await screen.findByText('An S-corp would save about $3,700 a year at your profit.')).toBeInTheDocument();
    expect(screen.getAllByText('+$3,684').length).toBeGreaterThan(0);
    expect(screen.getByText('2026 tax rules')).toBeInTheDocument();
    expect(screen.getByText("Includes California's S-corp franchise tax, employer unemployment and training taxes, and SDI on the salary.")).toBeInTheDocument();
    expect(screen.getByText('With a 50% salary and $1,500 a year for payroll and the extra return.')).toBeInTheDocument();
    expect(screen.getByText('Talk the salary through with a tax professional before deciding.')).toBeInTheDocument();
  });
  it('has short row headers, and stacks one block per point for narrow screens instead of a wide table', async () => {
    stubFetch({ '/api/business/s-corp': { available: true, year: 2026, line: 'An S-corp would save about $4,800 a year at your profit.', worth_it: true, salary_pct: 50, cost_cents: 150000, rules_note: '2026 tax rules', state_note: '',
      points: ['low', 'middle', 'high'].map((label, i) => ({ label, profit_cents: (i + 1) * 5000000, salary_cents: 0, sole_tax_cents: 2000000 + i, scorp_tax_cents: 1500000, cost_cents: 150000, saves_cents: 350000 + i * 100, payroll_cents: 0, franchise_cents: 0, sdi_cents: 0, unemployment_cents: 0 })) } });
    const { container } = wrapBook(<SCorpCard year={2026} />);
    await screen.findByText('An S-corp would save about $4,800 a year at your profit.');
    const table = container.querySelector('table.biz-table.biz-table--wide');
    expect(table).not.toBeNull();
    const headers = Array.from(table!.querySelectorAll('th[scope="row"]')).map((th) => th.textContent);
    expect(headers).toEqual(['Profit', 'Tax as a sole proprietor', 'Tax with an S-corp', 'S-corp saves']);
    const blocks = container.querySelectorAll('.biz-points > .biz-point');
    expect(blocks).toHaveLength(3);
    const high = within(blocks[2] as HTMLElement);
    expect(high.getByText('High')).toBeInTheDocument();
    expect(high.getByText('S-corp saves')).toBeInTheDocument();
    expect(high.getByText('+$3,502')).toBeInTheDocument();
    expect(high.getByText('$150,000')).toBeInTheDocument();
  });
  it('gives the reason when there is nothing to compare', async () => {
    stubFetch({ '/api/business/s-corp': { available: false, reason: 'Add both birth dates, your state and how you file taxes in Set up first.' } });
    wrapBook(<SCorpCard year={2026} />);
    expect(await screen.findByText('Add both birth dates, your state and how you file taxes in Set up first.')).toBeInTheDocument();
  });
});
