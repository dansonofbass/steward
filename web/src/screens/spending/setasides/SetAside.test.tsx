import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { SetAsideDetail } from '../../../api/types';
import { callsTo, renderAt, reply, stubFetch, type Route as StubRoute } from '../../../test-utils';
import { HEATER_DETAIL, HEATER_PAID, PROPTAX_DETAIL } from './fixtures';
import { SetAside } from './SetAside';

afterEach(() => vi.unstubAllGlobals());
const ACCOUNTS = { accounts: [
  { id: 21, name: 'House fund', type: 'savings', owner: 'joint', source: 'manual', institution: 'Manual', is_active: true, balance_cents: 410_000, as_of: '2026-10-24', stale_days: 1 },
  { id: 22, name: 'Kids fund', type: 'savings', owner: 'joint', source: 'manual', institution: 'Manual', is_active: true, balance_cents: 60_000, as_of: '2026-10-24', stale_days: 1 },
  { id: 23, name: 'Brokerage', type: 'brokerage_taxable', owner: 'joint', source: 'manual', institution: 'Manual', is_active: true, balance_cents: 1, as_of: '2026-10-24', stale_days: 1 },
] };
const NO_CONTENT = () => new Response(null, { status: 204 });
/** What the server's POST /setasides/estimate answers for an edit of Property tax with a new amount. */
const PREVIEW = { kind: 'twice_yearly', amount_cents: 430_000, monthly_cents: 71_700, yearly_cents: 860_000, first_month: '2026-11-01', next_due: '2026-11-01', months: 1, should_cents: 421_200 };
const HEATER_FLAGGED = { ...HEATER_DETAIL, estimate: { ...HEATER_DETAIL.estimate!, to_check: true } };

function page(id: number, routes: Record<string, StubRoute> = {}, detail: SetAsideDetail | (() => Response) = PROPTAX_DETAIL, book = {}) {
  const fetchMock = stubFetch({ [`/api/setasides/${id}`]: detail, '/api/accounts': ACCOUNTS, 'POST /api/setasides/estimate': PREVIEW, ...routes });
  renderAt(<Routes><Route path="/b/ours/spending/setasides/:id" element={<SetAside />} /></Routes>, book, `/spending/setasides/${id}`);
  return fetchMock;
}

describe('one set-aside', () => {
  it('shows the head, the schedule, the fund card and the matched payments in the list words', async () => {
    page(1);
    expect(await screen.findByRole('heading', { level: 1, name: 'Property tax' })).toBeInTheDocument();
    expect(screen.getByTestId('sa-detail-head')).toHaveTextContent('$702 a month');
    expect(screen.getByTestId('sa-detail-line')).toHaveTextContent(/^\$4,210 twice a year\s*·\s*\$8,420 a year\s*·\s*County Tax Collector$/);
    expect(screen.getByTestId('sa-detail-state')).toHaveTextContent('Due Nov 1, in 7 days · $110 short · House fund');
    const dues = screen.getAllByTestId('sa-due');
    expect(dues[0]).toHaveTextContent('Nov 1, 2026');
    expect(dues[0]).toHaveTextContent('In 7 days · first installment');
    expect(dues[0]).toHaveClass('is-next');
    expect(dues[1]).toHaveTextContent('Apr 10, 2027');
    expect(dues[1]).toHaveTextContent('In 6 months · second installment');
    const fund = screen.getByTestId('sa-fund');
    expect(fund).toHaveTextContent('House fund');
    expect(fund).toHaveTextContent('$110 short for Nov 1 · $4,210 due, $4,100 put away');
    expect(fund).toHaveTextContent('$4,212 should be by now: $702 a month, May to October, since the April payment');
    expect(fund).toHaveTextContent('This account is also linked to Water heater and Roof; money goes to the soonest due first.');
    expect(fund).not.toHaveTextContent('balance from');
    expect(fund.querySelector('.sp-pace__fill')).toHaveStyle({ width: '97%' });
    const pays = screen.getAllByTestId('sa-payment');
    expect(pays).toHaveLength(3);
    expect(pays[0]).toHaveTextContent('County Tax Collector');
    expect(pays[0]).toHaveTextContent('−$4,210.00');
    expect(pays[0]).toHaveTextContent('Apr 10, 2026 · Checking · Taxes · matched to the Apr 10 installment');
    expect(pays[1]).toHaveTextContent('matched to the Nov 1 installment, 2 days late');
    expect(screen.getByText('3 payments matched')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Setting aside' })).toHaveAttribute('href', '/b/ours/spending/setasides');
  });

  it('says "balance from Oct 12" only when the server says the balance is stale', async () => {
    page(1, {}, { ...PROPTAX_DETAIL, account: { ...PROPTAX_DETAIL.account!, as_of: '2026-10-12', stale: true } });
    expect(await screen.findByTestId('sa-fund')).toHaveTextContent('balance from Oct 12');
    expect(screen.getByTestId('sa-detail-state')).toHaveTextContent('House fund, balance from Oct 12');
  });

  it('Not this one undoes a match, and Stop archives after a confirmation', async () => {
    const fetchMock = page(1, { 'DELETE /api/setasides/match/301': NO_CONTENT, 'DELETE /api/setasides/1': NO_CONTENT });
    const pays = await screen.findAllByTestId('sa-payment');
    fireEvent.click(within(pays[0]).getByRole('button', { name: 'Not this one: the Apr 10 payment to County Tax Collector' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/setasides/match/301')).toHaveLength(1));
    const stop = screen.getByRole('button', { name: 'Stop setting this aside' });
    stop.focus();
    fireEvent.click(stop);
    expect(await screen.findByRole('dialog', { name: 'Stop setting Property tax aside?' })).toHaveTextContent('It leaves the list and the Plan. The payments already matched to it stay as they are.');
    expect(callsTo(fetchMock, 'DELETE', '/api/setasides/1')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Stop setting it aside' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/setasides/1')).toHaveLength(1));
    // THO-1: the stop is said as it happens, and focus goes to the name rather than <body>.
    const said = await screen.findByText(/^This set-aside was stopped on /);
    expect(said.closest('[aria-live]')).not.toBeNull();
    await waitFor(() => expect(screen.getByRole('heading', { level: 1, name: 'Property tax' })).toHaveFocus());
  });

  it('each Not this one names its payment, and a stopped set-aside answering 409 says so', async () => {
    page(1, { 'DELETE /api/setasides/match/302': () => reply({ error: 'That set-aside was stopped.' }, 409) });
    const buttons = await screen.findAllByRole('button', { name: /^Not this one/ });
    expect(buttons.map((b) => b.getAttribute('aria-label'))).toEqual([
      'Not this one: the Apr 10 payment to County Tax Collector', 'Not this one: the Nov 3 payment to County Tax Collector', 'Not this one: the Apr 9 payment to County Tax Collector']);
    fireEvent.click(buttons[1]);
    expect(await screen.findByText('That set-aside was stopped.')).toBeInTheDocument();
  });

  it('Edit opens the sheet filled in, asks the server for the figures, and Save sends only what changed', async () => {
    const fetchMock = page(1, { 'PUT /api/setasides/1': PROPTAX_DETAIL });
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const sheet = await screen.findByRole('dialog', { name: 'Edit Property tax' });
    expect(within(sheet).getByLabelText('What is it')).toHaveValue('Property tax');
    expect(within(sheet).getByRole('radio', { name: 'Twice a year' })).toHaveAttribute('aria-checked', 'true');
    expect(within(sheet).getByLabelText('Each installment')).toHaveValue('4,210');
    expect(within(sheet).getByLabelText('Put away in')).toHaveValue('21');
    expect(within(sheet).getByLabelText('Put away in').querySelectorAll('option')).toHaveLength(3);       // no account, House fund, Kids fund: the brokerage is not cash
    expect(within(sheet).getByLabelText('Matches payments to')).toHaveValue('County Tax Collector · Taxes');
    fireEvent.change(within(sheet).getByLabelText('Each installment'), { target: { value: '4,300' } });
    const preview = await within(sheet).findByTestId('sa-preview');
    await waitFor(() => expect(preview).toHaveTextContent('$717 a month'));
    expect(preview).toHaveTextContent('From November · next due Nov 1, 2026');
    expect(preview).toHaveTextContent('Spread over 1 month · $4,212 should be by now');
    expect(within(sheet).getByText('$8,600 a year · $717 a month')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/setasides/estimate').at(-1)?.body).toEqual({ amount_cents: 430_000, set_aside_id: 1 });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/setasides/1')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PUT', '/api/setasides/1')[0].body).toEqual({ amount_cents: 430_000 });
  });

  it('changing the account sends the account alone, and a bad amount is refused before it is sent', async () => {
    const fetchMock = page(1, { 'PUT /api/setasides/1': PROPTAX_DETAIL });
    fireEvent.click(await screen.findByRole('button', { name: 'Change the account' }));
    const sheet = await screen.findByRole('dialog', { name: 'Edit Property tax' });
    fireEvent.change(within(sheet).getByLabelText('Each installment'), { target: { value: '0' } });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Save' }));
    expect(await within(sheet).findByText('Enter an amount from $0.01 to $1,000,000.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'PUT', '/api/setasides/1')).toHaveLength(0);
    fireEvent.change(within(sheet).getByLabelText('Each installment'), { target: { value: '4,210' } });
    fireEvent.change(within(sheet).getByLabelText('Put away in'), { target: { value: '22' } });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/setasides/1')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PUT', '/api/setasides/1')[0].body).toEqual({ account_id: 22 });
  });

  it('an estimated one-off says its tag is dropped when the server says the figures are no longer the estimate', async () => {
    const fetchMock = page(6, { 'PUT /api/setasides/6': HEATER_DETAIL, 'POST /api/setasides/estimate': { kind: 'one_off', is_estimate: false, amount_cents: 250_000, monthly_cents: 9_600, first_month: '2026-11-01', next_due: '2028-12-01', months: 26, should_cents: 0 } }, HEATER_DETAIL);
    fireEvent.click(await screen.findByRole('button', { name: 'Change the amount' }));
    const sheet = await screen.findByRole('dialog', { name: 'Edit Water heater' });
    fireEvent.change(within(sheet).getByLabelText('About how much'), { target: { value: '2,500' } });
    expect(await within(sheet).findByTestId('sa-tag-drops')).toHaveTextContent('the Estimate tag is dropped');
    expect(callsTo(fetchMock, 'POST', '/api/setasides/estimate').at(-1)?.body).toEqual({ amount_cents: 250_000, set_aside_id: 6 });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/setasides/6')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PUT', '/api/setasides/6')[0].body).toEqual({ amount_cents: 250_000 });
  });

  it('not paid: the head says so, Find the payment filters Transactions, and It was not due skips the installment', async () => {
    const notPaid = { ...PROPTAX_DETAIL, state: 'not_paid' as const, missed_due: '2026-11-01', next_due: '2027-04-10', days_until: 117, short_cents: 0,
      dues: [{ due_on: '2026-11-01', status: 'missed' as const, which: 'first' as const, amount_cents: 421_000, paid_on: null, days_late: null, days_until: -43 }, { ...PROPTAX_DETAIL.dues[1], days_until: 117 }] };
    const fetchMock = page(1, { 'POST /api/setasides/1/skip': PROPTAX_DETAIL }, { ...notPaid, as_of: '2026-12-14', find_from: '2026-09-17', find_to: '2026-12-14' });
    expect(await screen.findByTestId('sa-detail-state')).toHaveTextContent('Nov 1 not paid yet · 6 weeks ago');
    expect(screen.getAllByTestId('sa-due')[0]).toHaveTextContent('Not paid yet · 6 weeks ago · first installment');
    expect(screen.getAllByTestId('sa-due')[0]).toHaveClass('is-missed');
    const notice = screen.getByTestId('sa-not-paid');
    expect(notice).toHaveTextContent('No payment to County Tax Collector under Taxes since Nov 1. If it was paid from another account or under another name, pick the payment and Steward will match it.');
    expect(within(notice).getByRole('link', { name: 'Find the payment' })).toHaveAttribute('href', '/b/ours/transactions?dates=custom&from=2026-09-17&to=2026-12-14&q=County+Tax+Collector');
    expect(screen.getByTestId('sa-fund')).toHaveTextContent('House fund keeps the $4,210; "should be by now" keeps counting from April until the installment is paid.');
    fireEvent.click(within(notice).getByRole('button', { name: 'It was not due: the Nov 1 installment' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/setasides/1/skip')[0].body).toEqual({ due_on: '2026-11-01' }));
  });

  it('paid late reads so on the head, the schedule and the payment', async () => {
    const late = { ...PROPTAX_DETAIL, state: 'on_track' as const, next_due: '2027-04-10', days_until: 167, short_cents: 0, should_cents: 0,
      dues: [{ due_on: '2026-11-01', status: 'late' as const, which: 'first' as const, amount_cents: 421_000, paid_on: '2026-11-20', days_late: 19, days_until: -19 }, PROPTAX_DETAIL.dues[1]],
      payments: [{ ...PROPTAX_DETAIL.payments[0], transaction_id: 305, posted_at: '2026-11-20', due_on: '2026-11-01', late: true, days_late: 19 }] };
    page(1, {}, late);
    expect((await screen.findAllByTestId('sa-due'))[0]).toHaveTextContent('Paid Nov 20, late · 19 days after · first installment');
    expect(screen.getAllByTestId('sa-due')[0]).toHaveClass('is-late');
    expect(screen.getByTestId('sa-detail-state')).toHaveTextContent('Nov 1 paid Nov 20, late · next Apr 10, 2027');
    expect(screen.getAllByTestId('sa-payment')[0]).toHaveTextContent('matched to the Nov 1 installment, 19 days late');
  });

  it('an estimate shows its own sources, and what is to be checked, instead of the schedule', async () => {
    const fetchMock = page(6, {}, HEATER_DETAIL);
    expect(await screen.findByRole('heading', { level: 1, name: /Water heater/ })).toHaveTextContent('Estimate');
    expect(screen.getByTestId('sa-detail-line')).toHaveTextContent(/^\$2,200 once\s*·\s*Planned for Dec 2028, 26 months away$/);
    const basis = screen.getByTestId('sa-basis');
    expect(basis).toHaveTextContent('Usually lasts10 to 15 years');
    expect(basis).toHaveTextContent('So, likely by2028 · planned for Dec 2028');
    expect(basis).toHaveTextContent('Typical cost to replace$1,500 to $3,000');
    expect(basis).toHaveTextContent('Set aside for$2,200 · $85 a month, Nov 2026 to Dec 2028');
    expect(within(basis).getByText('Cost to be checked')).toBeInTheDocument();          // the stored flag says so at once
    expect(basis).toHaveTextContent('Installed2014 · 12 years old');
    expect(within(basis).getByText('Lifespan: Typical water heater lifespan')).toBeInTheDocument();
    expect(within(basis).queryByText(/Typical water heater cost/)).toBeNull();          // an unchecked figure is never shown as sourced
    expect(fetchMock.mock.calls.map((c) => String(c[0]))).toEqual(expect.arrayContaining([expect.stringMatching(/setasides\/6$/)]));
    expect(callsTo(fetchMock, 'POST', '/api/setasides/estimate')).toHaveLength(0);   // one GET, no estimate call for the evidence
    expect(screen.queryByTestId('sa-due')).toBeNull();
    expect(screen.getByTestId('sa-fund')).toHaveTextContent('On track · nothing should be by now');
    expect(screen.getByTestId('sa-fund')).toHaveTextContent('$85 a month from November, $2,200 by Dec 2028');
    expect(screen.getByText('Nothing has been paid from it.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Change the year' }));
    expect(await screen.findByRole('dialog', { name: 'Edit Water heater' })).toBeInTheDocument();
  });

  it('says neither figure is checked when the server flags both', async () => {
    page(6, {}, { ...HEATER_FLAGGED, estimate: { ...HEATER_FLAGGED.estimate!, cost_to_check: true } });
    const basis = await screen.findByTestId('sa-basis');
    expect(within(basis).getByTestId('sa-sources')).toHaveTextContent('Lifespan to be checkedCost to be checked');
    expect(within(basis).queryByText(/^Lifespan: /)).toBeNull();
  });

  it('a paid one-off offers the next one in the server\'s figures; Start replaces it', async () => {
    const fetchMock = page(6, { 'POST /api/setasides/6/replace': HEATER_DETAIL }, HEATER_PAID);
    expect(await screen.findByTestId('sa-detail-state')).toHaveTextContent('Replaced Mar 14, 2028 · $2,350 paid from House fund');
    const offer = screen.getByTestId('sa-replace');
    expect(offer).toHaveTextContent('Water heater replaced Mar 2028 for $2,350. Start setting aside for the next one, about 2042? That is $2,350 over the months to Dec 2042, about $13 a month');
    fireEvent.click(within(offer).getByRole('button', { name: 'Start' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/setasides/6/replace')).toHaveLength(1));
  });

  it('Start goes to the new set-aside, not back to the stopped one', async () => {
    const fetchMock = page(6, { 'POST /api/setasides/6/replace': { ...HEATER_DETAIL, id: 8, name: 'Water heater (next)' }, '/api/setasides/8': { ...HEATER_DETAIL, id: 8, name: 'Water heater (next)' } }, HEATER_PAID);
    fireEvent.click(within(await screen.findByTestId('sa-replace')).getByRole('button', { name: 'Start' }));
    expect(await screen.findByRole('heading', { level: 1, name: /Water heater \(next\)/ })).toBeInTheDocument();
    expect(fetchMock.mock.calls.map((c) => String(c[0]))).toEqual(expect.arrayContaining([expect.stringMatching(/setasides\/8$/)]));
  });

  it('a set-aside that does not read as stored cannot be saved from the sheet, and does not fall back to Add', async () => {
    const fetchMock = page(1, { 'PUT /api/setasides/1': PROPTAX_DETAIL }, { ...PROPTAX_DETAIL, amount_cents: 0 });
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const sheet = await screen.findByRole('dialog', { name: 'Edit Property tax' });
    expect(within(sheet).getByTestId('sa-unreadable')).toHaveTextContent('Enter an amount from $0.01 to $1,000,000.');
    expect(within(sheet).getByRole('button', { name: 'Save' })).toBeDisabled();
    fireEvent.change(within(sheet).getByLabelText('Each installment'), { target: { value: '4,300' } });
    fireEvent.submit(within(sheet).getByTestId('sa-form'));
    await new Promise((res) => setTimeout(res, 500));
    expect(callsTo(fetchMock, 'PUT', '/api/setasides/1')).toHaveLength(0);
    expect(callsTo(fetchMock, 'POST', '/api/setasides/estimate')).toHaveLength(0);
  });

  it('No, archive it asks first, then stops the paid one-off; with no offer there is nothing to Start', async () => {
    const fetchMock = page(6, { 'DELETE /api/setasides/6': NO_CONTENT }, { ...HEATER_PAID, replace_offer: null });
    const offer = await screen.findByTestId('sa-replace');
    expect(offer).toHaveTextContent('It has no typical lifespan to estimate the next one from');
    expect(within(offer).queryByRole('button', { name: 'Start' })).toBeNull();
    fireEvent.click(within(offer).getByRole('button', { name: 'No, archive it' }));
    expect(await screen.findByRole('dialog', { name: 'Stop setting Water heater aside?' })).toHaveTextContent('It leaves the list and the Plan.');
    expect(callsTo(fetchMock, 'DELETE', '/api/setasides/6')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Stop setting it aside' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/setasides/6')).toHaveLength(1));
  });

  it('a viewer sees everything and changes nothing', async () => {
    page(1, {}, PROPTAX_DETAIL, { role: 'viewer' });
    await screen.findAllByTestId('sa-payment');
    for (const name of ['Edit', 'Stop setting this aside', 'Change the account']) expect(screen.queryByRole('button', { name })).toBeNull();
    expect(screen.queryByRole('button', { name: /^Not this one/ })).toBeNull();
  });

  it('a viewer of a missed installment gets no Find the payment or It was not due', async () => {
    page(1, {}, { ...PROPTAX_DETAIL, state: 'not_paid', missed_due: '2026-11-01' }, { role: 'viewer' });
    expect(await screen.findByTestId('sa-not-paid')).toHaveTextContent('No payment found');
    expect(screen.queryByRole('link', { name: 'Find the payment' })).toBeNull();
    expect(screen.queryByRole('button', { name: /It was not due/ })).toBeNull();
  });

  it('a stopped set-aside says so and offers no change, undo included', async () => {
    page(1, {}, { ...PROPTAX_DETAIL, archived_at: '2026-10-25T19:00:00+00:00' });
    expect(await screen.findByText(/^This set-aside was stopped on Oct 25/)).toBeInTheDocument();
    await screen.findAllByTestId('sa-payment');
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(screen.queryByRole('button', { name: /^Not this one/ })).toBeNull();
  });

  it('a set-aside stopped late in the evening says the local day, not the UTC one', async () => {
    const evening = new Date(2026, 9, 25, 23, 30).toISOString();          // 11:30 pm local; west of UTC, the UTC day is Oct 26
    page(1, {}, { ...PROPTAX_DETAIL, archived_at: evening });
    expect(await screen.findByText(/^This set-aside was stopped on Oct 25\./)).toBeInTheDocument();
  });

  it('a missing set-aside is not found', async () => {
    page(9, {}, () => reply({ error: 'No such set-aside.' }, 404));
    expect(await screen.findByText('No such set-aside.')).toBeInTheDocument();
  });
});
