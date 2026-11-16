import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, reply, stubFetch, wrap, wrapBook } from '../../test-utils';
import { nextDollarFixture } from './fixtures';
import { figures, NextDollar, parseRatePct } from './NextDollar';

afterEach(() => vi.unstubAllGlobals());

const routes = (extra: Record<string, unknown> = {}) => stubFetch({
  '/api/next-dollar': nextDollarFixture(),
  'POST /api/facts': (_u: string, init: RequestInit) => reply({ ...JSON.parse(init.body as string), as_of: '2026-10-13', note: null }, 201),
  'PATCH /api/accounts/': { id: 7, rate_bp: 1999 },
  ...extra,
});

describe('Next dollar', () => {
  it('lists the steps in order with their status, figures and sentence', async () => {
    routes();
    wrap(<NextDollar />);
    expect(await screen.findByRole('heading', { name: 'Next dollar' })).toBeInTheDocument();
    const cash = await screen.findByTestId('nd-cash');
    expect(cash).toHaveTextContent('1 Cash for 6 months of spending');   // THO-10: not "1Cash"
    expect(cash).toHaveTextContent('To do');
    expect(cash).toHaveTextContent('Cash now$20,000');
    expect(cash).toHaveTextContent('Still to add$16,000');
    expect(cash).toHaveTextContent('because business income is uncertain');
    expect(screen.getByTestId('nd-debt')).toHaveTextContent('Owed$4,800');
    expect(screen.getByTestId('nd-invest')).toHaveTextContent('5 Taxable investing');
    expect(screen.getByTestId('nd-invest')).toHaveTextContent('In this year$2,500');
    const roth = screen.getByTestId('nd-retirement');
    expect(roth).toHaveTextContent('No room');
    expect(roth).not.toHaveTextContent('Room left');
    expect(screen.getByText('Steward suggests; it never moves money.')).toBeInTheDocument();
    expect(screen.getByText('Cash target: 6 months of spending. Debt rate: above 7%.')).toBeInTheDocument();
  });

  it('labels a limit with its rules year', () => {
    const s = { ...nextDollarFixture().steps[3], status: 'to_do' as const, room_cents: 750_000 };
    expect(figures(s)).toEqual([{ label: 'In this year', cents: 0 }, { label: 'Room left (2026 limits)', cents: 750_000 }]);
  });

  it('asks the HSA question and sends the answer', async () => {
    const fetch = routes();
    wrap(<NextDollar />);
    const hsa = await screen.findByTestId('nd-hsa');
    fireEvent.click(within(hsa).getByRole('button', { name: 'Yes' }));
    await waitFor(() => expect(callsTo(fetch, 'POST', '/api/facts')).toHaveLength(1));
    expect(callsTo(fetch, 'POST', '/api/facts')[0].body).toEqual({ key: 'health.hsa_plan', value: 'yes' });
    await waitFor(() => expect(callsTo(fetch, 'GET', '/api/next-dollar').length).toBeGreaterThanOrEqual(2));
  });

  it('accepts a trailing % and refuses a comma', async () => {
    const fetch = routes();
    wrap(<NextDollar />);
    const debt = await screen.findByTestId('nd-debt');
    const box = within(debt).getByLabelText('Store card rate (%)');
    fireEvent.change(box, { target: { value: '22,9' } });
    fireEvent.click(within(debt).getByRole('button', { name: 'Save' }));
    expect(await within(debt).findByText('Enter a rate from 0 to 100.')).toBeInTheDocument();
    expect(callsTo(fetch, 'PATCH', '/api/accounts/')).toHaveLength(0);
    fireEvent.change(box, { target: { value: '19.99 %' } });
    fireEvent.click(within(debt).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(callsTo(fetch, 'PATCH', '/api/accounts/7')).toHaveLength(1));
    expect(callsTo(fetch, 'PATCH', '/api/accounts/7')[0].body).toEqual({ rate_bp: 1999 });
  });

  it('parses rates the way people type them', () => {
    expect([parseRatePct('7'), parseRatePct('19.99'), parseRatePct(' 22.9% '), parseRatePct('0')]).toEqual([700, 1999, 2290, 0]);
    expect([parseRatePct(''), parseRatePct('22,9'), parseRatePct('101'), parseRatePct('-3'), parseRatePct('abc')]).toEqual([null, null, null, null, null]);
  });

  it('changes the settings through facts', async () => {
    const fetch = routes();
    wrap(<NextDollar />);
    fireEvent.click(await screen.findByRole('button', { name: 'Change' }));
    const dialog = await screen.findByRole('dialog', { name: 'Next dollar settings' });
    const months = within(dialog).getByLabelText('Months of spending to keep in cash');
    fireEvent.change(months, { target: { value: '0' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    expect(await within(dialog).findByText('Enter whole months from 1 to 24.')).toBeInTheDocument();
    expect(callsTo(fetch, 'POST', '/api/facts')).toHaveLength(0);
    fireEvent.change(months, { target: { value: '9' } });
    fireEvent.change(within(dialog).getByLabelText('Pay down debt above this rate (%)'), { target: { value: '8' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(callsTo(fetch, 'POST', '/api/facts')).toHaveLength(2));
    expect(callsTo(fetch, 'POST', '/api/facts').map((c) => c.body)).toEqual([
      { key: 'next_dollar.cash_months', value: '9' }, { key: 'next_dollar.debt_rate_bp', value: '800' }]);
  });

  it('opens the backdoor Roth sheet when there is no Roth room', async () => {
    routes();
    wrap(<NextDollar />);
    fireEvent.click(await screen.findByRole('button', { name: 'If your income is too high for a Roth' }));
    expect(await screen.findByRole('dialog', { name: 'A Roth when income is too high' })).toHaveTextContent('backdoor Roth');
  });

  it('shows a viewer the steps without anything to change', async () => {
    routes();
    wrapBook(<NextDollar />, { role: 'viewer' });
    expect(await screen.findByTestId('nd-hsa')).toHaveTextContent('Does your health plan qualify for an HSA?');
    expect(screen.queryByRole('button', { name: 'Yes' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Change' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Store card rate (%)')).not.toBeInTheDocument();
  });

  it('shows no room figure for a step that waits for October (final review minor c)', () => {
    const s = { ...nextDollarFixture().steps[3], title: 'Solo 401(k)', status: 'later' as const, choice: 'business_plan' as const, room_cents: null, in_cents: 0 };
    expect(figures(s)).toEqual([{ label: 'In this year', cents: 0 }]);
    expect(figures({ ...s, room_cents: 2_000_000 })).toEqual([{ label: 'In this year', cents: 0 }]);
  });

  const withPayroll = (cents: number | null) => {
    const d = nextDollarFixture();
    d.steps[1] = { ...d.steps[1], status: 'to_do', why: '$1,200 in so far; the 2026 family limit is $8,750.', in_cents: 120_000,
      room_cents: cents === null ? null : 875_000 - 120_000 - cents, rules_year: 2026, payroll: { key: 'jr.payroll_hsa_cents', cents } };
    return d;
  };

  it('asks what the paycheck puts into the HSA and saves it as a fact (final review ruling I3)', async () => {
    const fetch = routes({ '/api/next-dollar': withPayroll(null) });
    wrap(<NextDollar />);
    const hsa = await screen.findByTestId('nd-hsa');
    expect(hsa).toHaveTextContent("Add what your paycheck puts in to see what's left.");
    expect(hsa).not.toHaveTextContent('Room left');
    fireEvent.change(within(hsa).getByLabelText('Put in through payroll this year'), { target: { value: '6,000' } });
    fireEvent.click(within(hsa).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(callsTo(fetch, 'POST', '/api/facts')).toHaveLength(1));
    expect(callsTo(fetch, 'POST', '/api/facts')[0].body).toEqual({ key: 'jr.payroll_hsa_cents', value: '600000' });
  });

  it('shows an entered payroll amount in the box and the room again', async () => {
    routes({ '/api/next-dollar': withPayroll(600_000) });
    wrap(<NextDollar />);
    const hsa = await screen.findByTestId('nd-hsa');
    expect(hsa).not.toHaveTextContent("Add what your paycheck puts in");
    expect(hsa).toHaveTextContent('Room left (2026 limits)$1,550');
    expect(within(hsa).getByLabelText('Put in through payroll this year')).toHaveValue('6,000');
  });

  it('shows a viewer the payroll note without the box', async () => {
    routes({ '/api/next-dollar': withPayroll(null) });
    wrapBook(<NextDollar />, { role: 'viewer' });
    const hsa = await screen.findByTestId('nd-hsa');
    expect(hsa).toHaveTextContent("Add what your paycheck puts in to see what's left.");
    expect(within(hsa).queryByLabelText('Put in through payroll this year')).not.toBeInTheDocument();
  });

  it('shows the error in place of the list', async () => {
    routes({ '/api/next-dollar': () => reply({ error: "Next dollar couldn't be worked out right now." }, 503) });
    wrap(<NextDollar />);
    expect(await screen.findByText("Next dollar couldn't be worked out right now.")).toBeInTheDocument();
  });
});
