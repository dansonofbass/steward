import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, stubFetch, wrapBook } from '../../test-utils';
import type { QuarterlyOut } from './api';
import { QuarterlyCard } from './QuarterlyCard';

afterEach(() => vi.unstubAllGlobals());

const due = (d: string, label: string, inst: number, still: number, status: 'paid' | 'short' | 'upcoming' | 'nothing') =>
  ({ due: d, due_label: label, installment_cents: inst, by_then_cents: inst, paid_cents: 0, still_due_cents: still, status });

export const Q: QuarterlyOut = {
  available: true, year: 2026, prior_year: 2025, state: 'CA', state_name: 'California',
  rules_note: '2026 federal and 2025 California rules', never: 'Steward never pays or files anything.',
  profit: { low_cents: 6000000, high_cents: 10000000, entered: true }, low_tax_cents: 1300000,
  agencies: [
    { agency: 'federal', label: 'Federal (IRS)', method: 'prior_year', line: "110% of 2025's tax, $27,280: less than 90% of this year's ($31,500), and it still avoids the penalty.",
      withholding_line: 'Less $21,500 withheld from 2026 pay.', skip_line: 'You can skip the January 15 payment if you file your 2026 return by February 1, 2027 and pay the rest.',
      current_tax_cents: 3500000, current_required_cents: 3150000, prior_required_cents: 2728000, required_cents: 2728000, withholding_cents: 2150000,
      balance_cents: 578000, paid_cents: 400000,
      dues: [due('2026-04-15', 'April 15, 2026', 144500, 0, 'paid'), due('2026-06-15', 'June 15, 2026', 144500, 0, 'paid'),
             due('2026-09-15', 'September 15, 2026', 144500, 33500, 'short'), due('2027-01-15', 'January 15, 2027', 144500, 178000, 'upcoming')] },
    { agency: 'state', label: 'California (FTB)', method: 'current_year', line: "90% of this year's tax, $9,000: no more than 110% of 2025's ($10,010).",
      withholding_line: null, skip_line: null, current_tax_cents: 1000000, current_required_cents: 900000, prior_required_cents: 1001000,
      required_cents: 900000, withholding_cents: 720000, balance_cents: 180000, paid_cents: 0,
      dues: [due('2026-04-15', 'April 15, 2026', 54000, 54000, 'short'), due('2026-06-15', 'June 15, 2026', 72000, 126000, 'short'),
             due('2026-09-15', 'September 15, 2026', 0, 126000, 'nothing'), due('2027-01-15', 'January 15, 2027', 54000, 180000, 'upcoming')] },
  ],
  next: { due: '2027-01-15', due_label: 'January 15, 2027', federal_cents: 178000, state_cents: 180000 }, notice: null,
  payments: [{ id: 41, posted_at: '2026-04-14', posted_label: 'April 14, 2026', agency: 'federal', label: 'Federal (IRS)', amount_cents: 400000, counts: true, description: 'IRS USATAXPYMT' }],
  prior: { federal_tax_cents: 2480000, federal_agi_cents: 19850000, state_tax_cents: 910000, state_agi_cents: 19850000 },
  withholding: { federal_ytd_cents: 1610000, state_ytd_cents: 540000, as_of: '2026-09-30', as_of_label: 'September 30, 2026' }, has_wages: true, needs_withholding: false,
  notes: ["Interest, dividends, gains and itemized deductions such as mortgage interest aren't counted."], email_on: false,
};

describe('The quarterly taxes card', () => {
  it('leads with the next date and its amounts, then each agency and its dates', async () => {
    stubFetch({ '/api/taxes/quarterly': Q });
    wrapBook(<QuarterlyCard />);
    expect(await screen.findByRole('heading', { name: 'Quarterly taxes' })).toBeInTheDocument();
    expect(screen.getByText('Next due January 15, 2027')).toBeInTheDocument();
    expect(screen.getByText('$1,780')).toBeInTheDocument();
    expect(screen.getByText('$1,800')).toBeInTheDocument();
    expect(screen.getByText(Q.agencies[0].line)).toBeInTheDocument();
    expect(screen.getByText('Short $335')).toBeInTheDocument();
    expect(screen.getAllByText('Paid')).toHaveLength(2);
    expect(screen.getByText('Nothing due')).toBeInTheDocument();       // California's September date: no share of the year
    expect(screen.getAllByText('Due')).toHaveLength(2);                 // the two January dates
    expect(screen.getByText('2026 federal and 2025 California rules')).toBeInTheDocument();
    expect(screen.getByText('Steward never pays or files anything.')).toBeInTheDocument();
    expect(screen.getByText('At the low end of your range, this year\'s tax would be $13,000.')).toBeInTheDocument();
  });

  it('marks a payment as not an estimate', async () => {
    const fetchMock = stubFetch({ '/api/taxes/quarterly': Q,
      'PUT /api/taxes/payments/41': { ...Q, payments: [{ ...Q.payments[0], counts: false }] } });
    wrapBook(<QuarterlyCard />);
    fireEvent.click(await screen.findByRole('button', { name: 'Not an estimate' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/taxes/payments/41')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PUT', '/api/taxes/payments/41')[0].body).toEqual({ counts: false });
    expect(await screen.findByRole('button', { name: 'Count it' })).toBeInTheDocument();
  });

  it('asks for last year\'s return in whole cents', async () => {
    const fetchMock = stubFetch({ '/api/taxes/quarterly': { ...Q, prior: null }, 'PUT /api/taxes/return/2025': Q });
    wrapBook(<QuarterlyCard />);
    fireEvent.change(await screen.findByLabelText('Federal total tax (Form 1040 line 24, less refundable credits)'), { target: { value: '24,800.00' } });
    fireEvent.change(screen.getByLabelText('Federal adjusted gross income'), { target: { value: '198,500' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save the 2025 return' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/taxes/return/2025')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PUT', '/api/taxes/return/2025')[0].body).toEqual({
      federal_tax_cents: 2480000, federal_agi_cents: 19850000, state_tax_cents: null, state_agi_cents: null });
  });

  it('asks for withholding when there are wages and none is entered', async () => {
    const fetchMock = stubFetch({ '/api/taxes/quarterly': { ...Q, withholding: null, needs_withholding: true,
      notes: ['Add what your 2026 paychecks withheld; until then none of it is counted.'] }, 'PUT /api/taxes/withholding/2026': Q });
    wrapBook(<QuarterlyCard />);
    expect(await screen.findByText('Add what your 2026 paychecks withheld; until then none of it is counted.')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Federal withheld so far in 2026'), { target: { value: '16,100' } });
    fireEvent.change(screen.getByLabelText('California withheld so far in 2026'), { target: { value: '5,400' } });
    const payDate = screen.getByLabelText('Pay date on that 2026 stub');
    expect(payDate).toHaveAttribute('min', '2026-01-01');               // a later stub carries the next year's pay
    expect(payDate).toHaveAttribute('max', '2026-12-31');
    fireEvent.change(payDate, { target: { value: '2026-09-30' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save withholding' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/taxes/withholding/2026')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PUT', '/api/taxes/withholding/2026')[0].body).toEqual({
      federal_ytd_cents: 1610000, state_ytd_cents: 540000, as_of: '2026-09-30' });
  });

  it('turns the email on for this person only, off by default', async () => {
    const fetchMock = stubFetch({ '/api/taxes/quarterly': Q, 'PUT /api/taxes/email': { on: true } });
    wrapBook(<QuarterlyCard />);
    const box = await screen.findByRole('checkbox', { name: 'Email me two weeks before each due date' });
    expect(box).not.toBeChecked();
    fireEvent.click(box);
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/taxes/email')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PUT', '/api/taxes/email')[0].body).toEqual({ on: true });
  });

  it('a viewer sees no edit buttons but can still choose their email', async () => {
    stubFetch({ '/api/taxes/quarterly': Q });
    wrapBook(<QuarterlyCard />, { role: 'viewer' });
    await screen.findByRole('heading', { name: 'Quarterly taxes' });
    expect(screen.queryByRole('button', { name: 'Not an estimate' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Change' })).toBeNull();
    expect(screen.getByRole('checkbox', { name: 'Email me two weeks before each due date' })).toBeInTheDocument();
  });

  it('gives the reason when Taxes has nothing to show yet', async () => {
    stubFetch({ '/api/taxes/quarterly': { available: false, reason: 'Add both birth dates, your state and how you file taxes in Set up first.' } });
    wrapBook(<QuarterlyCard />);
    expect(await screen.findByText('Add both birth dates, your state and how you file taxes in Set up first.')).toBeInTheDocument();
  });
});
