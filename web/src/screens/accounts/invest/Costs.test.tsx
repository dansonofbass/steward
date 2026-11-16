import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BOOK, callsTo, reply, stubFetch, wrapBook } from '../../../test-utils';
import { acct } from '../fixtures';
import { PAGE, page } from './fixtures';
import Investment from './Investment';

afterEach(() => vi.unstubAllGlobals());

const RULE = "Enter the fund's expense ratio as a percent, like 0.04.";
const taxable = acct({ id: 3, name: 'Taxable', type: 'brokerage_taxable', institution: 'Robo Invest' });

describe('costs on the page (investment views spec, Costs)', () => {
  it('"cost unknown · Add" saves the ratio for that symbol and refreshes the page', async () => {
    const fetchMock = stubFetch({ '/api/accounts/3/investment': PAGE, 'PUT /api/expense-ratios': { symbol: 'ACMEX', ratio_pct: '0.45' } });
    wrapBook(<Investment account={taxable} />);
    const row = await screen.findByRole('row', { name: /ACMEX/ });
    expect(row).toHaveTextContent('cost unknown · Add');
    fireEvent.click(within(row).getByRole('button', { name: 'Add' }));
    fireEvent.change(within(row).getByLabelText('Expense ratio for ACMEX (% a year)'), { target: { value: '0.45' } });
    fireEvent.click(within(row).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/expense-ratios')[0]?.body).toEqual({ symbol: 'ACMEX', ratio_pct: '0.45' }));
    await waitFor(() => expect(callsTo(fetchMock, 'GET', '/api/accounts/3/investment')).toHaveLength(2));
  });

  it("shows the vault's words when a ratio is refused", async () => {
    stubFetch({ '/api/accounts/3/investment': PAGE, 'PUT /api/expense-ratios': () => reply({ error: RULE }, 422) });
    wrapBook(<Investment account={taxable} />);
    const row = await screen.findByRole('row', { name: /ACMEX/ });
    fireEvent.click(within(row).getByRole('button', { name: 'Add' }));
    fireEvent.change(within(row).getByLabelText('Expense ratio for ACMEX (% a year)'), { target: { value: '45' } });
    fireEvent.click(within(row).getByRole('button', { name: 'Save' }));
    expect(await within(row).findByText(RULE)).toBeInTheDocument();
  });

  it('a viewer sees "cost unknown" and the fee, with nothing to change', async () => {
    stubFetch({ '/api/accounts/3/investment': PAGE });
    wrapBook(<Investment account={taxable} />, { ...BOOK, role: 'viewer' });
    const row = await screen.findByRole('row', { name: /ACMEX/ });
    expect(within(row).getByText('cost unknown')).toBeInTheDocument();
    expect(within(row).queryByRole('button', { name: 'Add' })).toBeNull();
    expect(screen.getByText('Advisory fee 0.25%: about $450 a year.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Change' })).toBeNull();
  });

  it('sets an advisory fee on an account without one', async () => {
    const fetchMock = stubFetch({ '/api/accounts/3/investment': page({ advisory: null }), 'PATCH /api/accounts/3': { id: 3 } });
    wrapBook(<Investment account={taxable} />);
    expect(await screen.findByText('No advisory fee set.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Set' }));
    fireEvent.change(screen.getByLabelText('Advisory fee (% a year)'), { target: { value: '0.25' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/accounts/3')[0]?.body).toEqual({ advisory_fee_bp: 25 }));
  });

  it('clears the fee when the box is emptied, and catches one that isn\'t a percent before sending', async () => {
    const fetchMock = stubFetch({ '/api/accounts/3/investment': PAGE, 'PATCH /api/accounts/3': { id: 3 } });
    wrapBook(<Investment account={taxable} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Change' }));
    const box = screen.getByLabelText('Advisory fee (% a year)');
    expect(box).toHaveValue('0.25');
    fireEvent.change(box, { target: { value: 'abc' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Enter a fee between 0% and 3%.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'PATCH', '/api/accounts/3')).toHaveLength(0);
    fireEvent.change(box, { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/accounts/3')[0]?.body).toEqual({ advisory_fee_bp: null }));
  });

  it('takes a fee typed without the leading zero', async () => {
    const fetchMock = stubFetch({ '/api/accounts/3/investment': PAGE, 'PATCH /api/accounts/3': { id: 3 } });
    wrapBook(<Investment account={taxable} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Change' }));
    fireEvent.change(screen.getByLabelText('Advisory fee (% a year)'), { target: { value: '.25' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/accounts/3')[0]?.body).toEqual({ advisory_fee_bp: 25 }));
  });
});
