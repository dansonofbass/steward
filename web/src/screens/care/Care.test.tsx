import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BookSummary } from '../../api/types';
import { askState, resetAsk } from '../../ask/store';
import { callsTo, expectRemovalSaid, reply, stubFetch, wrapBook } from '../../test-utils';
import Care from './Care';
import { AT_HOME, CARE, MONTHLY, NOT_SET_UP, PARENT } from './fixtures';

afterEach(() => vi.unstubAllGlobals());
const mount = (book: Partial<BookSummary> = {}) =>
  wrapBook(<Care />, { ...PARENT, ...book }, '/b/margaret-ellis/care');

describe('The Care screen', () => {
  it('shows each scenario with how long the money lasts, its chart and the Medi-Cal line', async () => {
    stubFetch({ '/api/care': CARE });
    mount();
    expect(await screen.findByRole('heading', { name: 'Care', level: 1 })).toBeInTheDocument();
    expect(screen.getByText('For Margaret, 82')).toBeInTheDocument();
    expect(screen.getByText('Money lasts until 2032 (age 88)')).toBeInTheDocument();
    expect(screen.getByText('Money lasts until 2028 (age 84)')).toBeInTheDocument();
    expect(screen.getByText("$7,280 a month for care, in today's dollars")).toBeInTheDocument();
    expect(screen.getByText('Long-term care insurance pays from 2027 and runs out in 2030.')).toBeInTheDocument();
    expect(screen.getByText('Medi-Cal in 2027: Eligible after spending down $21,000 (2026 rules).')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Savings from $260,000 in 2026 to $0 in 2033. Runs out in 2033.' })).toBeInTheDocument();
    expect(screen.getByText('Meets the Medi-Cal limit in 2030')).toBeInTheDocument();
    expect(screen.getByText('An estimate to take to an elder-law attorney, not legal advice.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Read the rule' })).toHaveAttribute('href', CARE.medi_cal!.url!);
    expect(screen.getAllByText('Typical in California: CareScout Cost of Care Survey 2025, raised 4% a year to 2026.')).toHaveLength(2);
    expect(screen.getByText('Care costs rise 4% a year.')).toBeInTheDocument();
  });

  it('shows the year-by-year table with savings, care, insurance and Medi-Cal', async () => {
    stubFetch({ '/api/care': CARE });
    mount();
    const card = (await screen.findByRole('heading', { name: 'Assisted living from 2027' })).closest('.care-card') as HTMLElement;
    const rows = within(card).getAllByRole('row');
    expect(within(rows[2]).getAllByRole('cell').map((c) => c.textContent)).toEqual(['$151,000', '$87,360', '$41,250', '$0', 'Spend down $21,000']);
    expect(within(rows[4]).getByRole('rowheader')).toHaveTextContent('2029 (85)');
    expect(within(rows[4]).getAllByRole('cell')[0]).toHaveTextContent('Short $10,000');
  });

  it('lets a manager set Care up and sends whole numbers', async () => {
    const fetchMock = stubFetch({ '/api/care': NOT_SET_UP, 'PUT /api/care/setup': CARE });
    mount();
    expect(await screen.findByRole('heading', { name: 'Set up Care' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Year born'), { target: { value: '1944' } });
    fireEvent.change(screen.getByLabelText('Monthly spending'), { target: { value: '4,000' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/care/setup')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PUT', '/api/care/setup')[0].body).toEqual({
      person: 'margaret', birth_year: 1944, spouse_birth_year: null, state: 'CA', care_inflation_bp: 400, spending_monthly_cents: 400000,
    });
    expect(await screen.findByText('Money lasts until 2032 (age 88)')).toBeInTheDocument();
  });

  it('warns at the top of Scenarios when no spending is counted, and a manager can change setup from there', async () => {
    const NO_SPENDING = { ...CARE, spending: { monthly_cents: 0, months: 0, typed: false, line: 'Spending: none.' } };
    stubFetch({ '/api/care': NO_SPENDING });
    mount();
    const section = (await screen.findByRole('heading', { name: 'Scenarios' })).closest('section') as HTMLElement;
    const warning = within(section).getByRole('status');
    expect(warning).toHaveTextContent('No spending is counted yet, so every scenario lasts longer than it would. Add spending under Setup.');
    expect(warning.compareDocumentPosition(within(section).getAllByRole('listitem')[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(within(warning).getByRole('button', { name: 'Change setup' }));
    expect(await screen.findByRole('heading', { name: 'Set up Care' })).toBeInTheDocument();
  });

  it('shows no warning when spending is typed in, even as zero', async () => {
    stubFetch({ '/api/care': { ...CARE, spending: { monthly_cents: 0, months: 0, typed: true, line: 'Spending: $0 a month, typed in.' } } });
    mount();
    await screen.findByRole('heading', { name: 'Scenarios' });
    expect(screen.queryByText(/No spending is counted yet/)).toBeNull();
  });

  it('shows a viewer the warning without a button', async () => {
    stubFetch({ '/api/care': { ...CARE, spending: { monthly_cents: 0, months: 0, typed: false, line: 'Spending: none.' } } });
    mount({ role: 'viewer' });
    expect(await screen.findByText(/No spending is counted yet/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Change setup' })).toBeNull();
  });

  it('tells a viewer Care is not set up and offers no form', async () => {
    stubFetch({ '/api/care': NOT_SET_UP });
    mount({ role: 'viewer' });
    expect(await screen.findByText("Care isn't set up yet. A manager can set it up.")).toBeInTheDocument();
    expect(screen.queryByLabelText('Year born')).toBeNull();
  });
});

describe('Changing Care', () => {
  it('adds a scenario and sends whole numbers', async () => {
    const fetchMock = stubFetch({ '/api/care': CARE, 'POST /api/care/scenarios': () => reply(CARE, 201) });
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Add a scenario' }));
    fireEvent.click(screen.getByRole('radio', { name: 'In-home help' }));
    fireEvent.change(screen.getByLabelText('Hours a week'), { target: { value: '20' } });
    fireEvent.change(screen.getByLabelText('Adult day, days a week'), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('Family adds each month'), { target: { value: '500' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/care/scenarios')).toHaveLength(1));
    expect(callsTo(fetchMock, 'POST', '/api/care/scenarios')[0].body).toEqual({
      level: 'in_home_help', start_year: null, hours_week: 20, adult_day_days: 2, room: null, sell_home_year: null,
      home_price_cents: null, home_basis_cents: null, selling_cost_bp: 600, family_monthly_cents: 50000, spending_change_monthly_cents: 0,
    });
  });

  it('changes a scenario to sell the home', async () => {
    const fetchMock = stubFetch({ '/api/care': CARE, 'PATCH /api/care/scenarios/2': CARE });
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Change Assisted living from 2027' }));
    expect(screen.getByLabelText('Starts')).toHaveValue('2027');
    fireEvent.click(screen.getByRole('checkbox', { name: 'Sell the home' }));
    expect(screen.getByText("Leave blank to use $780,000, the home's value in the inventory.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Year sold'), { target: { value: '2028' } });
    fireEvent.change(screen.getByLabelText('Expected price'), { target: { value: '780,000' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/care/scenarios/2')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PATCH', '/api/care/scenarios/2')[0].body).toEqual({
      level: 'assisted_living', start_year: 2027, hours_week: null, adult_day_days: null, room: null, sell_home_year: 2028,
      home_price_cents: 78000000, home_basis_cents: null, selling_cost_bp: 600, family_monthly_cents: 0, spending_change_monthly_cents: 0,
    });
  });

  it('asks before removing a scenario', async () => {
    const fetchMock = stubFetch({ '/api/care': CARE, 'DELETE /api/care/scenarios/2': { ...CARE, scenarios: [AT_HOME] } });
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Remove Assisted living from 2027' }));
    expect(screen.getByText('Remove Assisted living from 2027?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Keep' })).toHaveFocus();   // the Remove that opened it is gone
    expect(callsTo(fetchMock, 'DELETE', '/api/care/scenarios/2')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Remove Assisted living from 2027' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/care/scenarios/2')).toHaveLength(1));
    await waitFor(() => expect(screen.queryByText('Money lasts until 2028 (age 84)')).toBeNull());
    await expectRemovalSaid('Removed Assisted living from 2027.', () => screen.getByRole('heading', { name: 'Scenarios' }));
  });

  it('Keep gives focus back to the scenario\'s own Remove', async () => {
    stubFetch({ '/api/care': CARE });
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Remove Assisted living from 2027' }));
    fireEvent.click(screen.getByRole('button', { name: 'Keep' }));
    expect(screen.queryByText('Remove Assisted living from 2027?')).toBeNull();
    expect(screen.getByRole('button', { name: 'Remove Assisted living from 2027' })).toHaveFocus();
  });

  it('enters a quote for a care cost and goes back to the typical figure', async () => {
    const quoted = { ...CARE, costs: CARE.costs.map((c) => (c.key === 'assisted_living_monthly'
      ? { ...c, text: '$6,450 a month', line: 'Your quote, October 2, 2026.', quote: { cents: 645000, quoted_on: '2026-10-02' } } : c)) };
    const fetchMock = stubFetch({ '/api/care': CARE, 'PUT /api/care/quotes/assisted_living_monthly': quoted,
      'DELETE /api/care/quotes/assisted_living_monthly': CARE });
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Enter a quote for Assisted living' }));
    fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '6,450' } });
    fireEvent.change(screen.getByLabelText('Date of the quote'), { target: { value: '2026-10-02' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/care/quotes/assisted_living_monthly')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PUT', '/api/care/quotes/assisted_living_monthly')[0].body).toEqual({ cents: 645000, quoted_on: '2026-10-02' });
    expect(await screen.findByText('Your quote, October 2, 2026.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Change quote for Assisted living' }));
    fireEvent.click(screen.getByRole('button', { name: 'Use the typical figure' }));
    fireEvent.click(within(screen.getByRole('group', { name: 'Remove your quote and use the typical figure?' })).getByRole('button', { name: 'Remove your quote for assisted living' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/care/quotes/assisted_living_monthly')).toHaveLength(1));
    const said = await screen.findByText('Removed your quote for assisted living. Care uses the typical figure.');
    expect(said.closest('[aria-live]')).not.toBeNull();
  });

  it('asks before dropping a quote for the typical figure, and Keep keeps it', async () => {
    const quoted = { ...CARE, costs: CARE.costs.map((c) => (c.key === 'assisted_living_monthly'
      ? { ...c, text: '$6,450 a month', line: 'Your quote, October 2, 2026.', quote: { cents: 645000, quoted_on: '2026-10-02' } } : c)) };
    const fetchMock = stubFetch({ '/api/care': quoted, 'DELETE /api/care/quotes/assisted_living_monthly': CARE });
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Change quote for Assisted living' }));
    fireEvent.click(screen.getByRole('button', { name: 'Use the typical figure' }));
    const ask = screen.getByRole('group', { name: 'Remove your quote and use the typical figure?' });
    expect(within(ask).getByText('Remove your quote and use the typical figure?')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'DELETE', '/api/care/quotes')).toHaveLength(0);
    fireEvent.click(within(ask).getByRole('button', { name: 'Keep' }));
    expect(screen.queryByRole('group', { name: 'Remove your quote and use the typical figure?' })).toBeNull();
    expect(screen.getByLabelText('Amount')).toHaveValue('6450');
    expect(callsTo(fetchMock, 'DELETE', '/api/care/quotes')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Use the typical figure' }));
    fireEvent.click(within(screen.getByRole('group', { name: 'Remove your quote and use the typical figure?' })).getByRole('button', { name: 'Remove your quote for assisted living' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/care/quotes/assisted_living_monthly')).toHaveLength(1));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('stops adding at five scenarios', async () => {
    const five = { ...CARE, scenarios: [1, 2, 3, 4, 5].map((id) => ({ ...AT_HOME, id, label: `At home as today ${id}` })) };
    stubFetch({ '/api/care': five });
    mount();
    expect(await screen.findByRole('button', { name: 'Add a scenario' })).toBeDisabled();
    expect(screen.getByText('Care compares up to 5 scenarios.')).toBeInTheDocument();
  });

  it('offers a viewer nothing to change', async () => {
    stubFetch({ '/api/care': CARE });
    mount({ role: 'viewer' });
    expect(await screen.findByText('Money lasts until 2032 (age 88)')).toBeInTheDocument();
    for (const name of [/Add a scenario/, /^Change /, /^Remove /, /Enter a quote/, /Change setup/]) {
      expect(screen.queryByRole('button', { name })).toBeNull();
    }
  });
});

describe('Month by month', () => {
  it('lists the next 60 days and recent months', async () => {
    stubFetch({ '/api/care': CARE });
    mount();
    expect(await screen.findByRole('heading', { name: 'Month by month' })).toBeInTheDocument();
    expect(screen.getByText('Southern California Edison')).toBeInTheDocument();
    expect(screen.getByText('Coming in $2,140 · Going out $90')).toBeInTheDocument();
    expect(screen.getByText('Cash above the low-balance floors: $300')).toBeInTheDocument();
    expect(screen.getByText('October 2026 so far')).toBeInTheDocument();
    expect(screen.getByText('In $3,525 · Out $1,200')).toBeInTheDocument();
    expect(screen.getByText('Groceries')).toBeInTheDocument();
  });

  it('warns when money comes up short, even before Care is set up', async () => {
    stubFetch({ '/api/care': { ...NOT_SET_UP, monthly: { ...MONTHLY, short_line: 'Short this month by $190', short_cents: 19000 } } });
    mount({ role: 'viewer' });
    expect(await screen.findByText('Short this month by $190')).toBeInTheDocument();
    expect(screen.getByText("Care isn't set up yet. A manager can set it up.")).toBeInTheDocument();
  });
});

describe('Ask about this on Care (P17)', () => {
  afterEach(() => { resetAsk(); });
  it('one beside the heading about the projection, and one on each scenario by its id', async () => {
    stubFetch({ '/api/care': CARE });
    mount({ chat: true });
    fireEvent.click(await screen.findByRole('button', { name: 'Ask about Care' }));
    expect(askState().about).toStrictEqual({ kind: 'care' });
    expect(askState().surface).toStrictEqual({ kind: 'care' });
    const s = CARE.scenarios[0];
    fireEvent.click(screen.getByRole('button', { name: `Ask about ${s.label}` }));
    expect(askState().about).toStrictEqual({ kind: 'care', id: s.id });
    expect(askState().surface).toStrictEqual({ kind: 'care-scenario' });
  });
  it('a viewer can ask about a scenario too', async () => {
    stubFetch({ '/api/care': CARE });
    mount({ chat: true, role: 'viewer' });
    expect(await screen.findByRole('button', { name: `Ask about ${CARE.scenarios[0].label}` })).toBeInTheDocument();
  });
});
