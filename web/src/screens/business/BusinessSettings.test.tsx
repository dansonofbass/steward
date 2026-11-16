import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, expectRemovalSaid, reply, stubFetch, wrapBook } from '../../test-utils';
import BusinessSettings, { ruleSentence } from './BusinessSettings';
import type { BusinessSettingsOut } from './api';

afterEach(() => vi.unstubAllGlobals());

const S: BusinessSettingsOut = {
  year: 2026, this_year: 2026, type: 'sole_prop', home_office: { method: 'simplified', office_sqft: 120, home_sqft: 0, home_costs_cents: 0 },
  car_method: 'standard', miles: [{ from: '2026-01-01', to: '2026-06-30', rate_tenths: 725, miles: 1200 }, { from: '2026-07-01', to: '2026-12-31', rate_tenths: 760, miles: 900 }],
  expect: null, s_corp: { salary_pct: 50, cost_cents: 150000 },
  owner: 'jr', adults: [{ key: 'jr', name: 'JR' }, { key: 'spouse', name: 'Sam' }],
  rules: { year: 2026, using_note: null, home_office_rate_cents: 500, home_office_max_sqft: 300, meals_pct: 50 },
};
const RULES = { rules: [
  { id: 1, kind: 'account', label: 'Business checking', account_id: 3, account_name: 'Business checking', pct: 100, line: null },
  { id: 2, kind: 'client', label: 'ACH CLIENT INV', account_id: null, account_name: null, pct: 100, line: null },
  { id: 3, kind: 'merchant', label: 'Mobile One', account_id: 2, account_name: 'Rewards Card', pct: 40, line: 'utilities' },
] };
const ACCOUNTS = { accounts: [{ id: 2, name: 'Rewards Card', type: 'credit', owner: 'joint', source: 'manual', institution: 'Manual', is_active: true, balance_cents: 0, as_of: null, stale_days: null }] };

describe('Settings, Business', () => {
  it('words each rule plainly', () => {
    expect(RULES.rules.map((r) => ruleSentence(r as never))).toEqual([
      'Everything in Business checking is business', 'ACH CLIENT INV is a client', 'Mobile One on Rewards Card: 40% business, Utilities']);
  });

  it('shows the settings with the rule year and saves the type at once', async () => {
    const fetchMock = stubFetch({ '/api/business/settings': S, '/api/business/rules': RULES, '/api/accounts': ACCOUNTS, 'PUT /api/business/settings': { ...S, type: 's_corp' } });
    wrapBook(<BusinessSettings />, {}, '/b/ours/settings/business');
    expect(await screen.findByText('$5 a square foot, up to 300 square feet (2026 rules).')).toBeInTheDocument();
    expect(screen.getByLabelText('Business miles, Jan 1 to Jun 30 (72.5¢ a mile)')).toHaveValue('1200');
    fireEvent.click(screen.getByRole('radio', { name: 'S-corp' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/business/settings')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PUT', '/api/business/settings')[0].body).toEqual({ type: 's_corp' });
  });

  it('saves miles and adds a whole-account rule', async () => {
    const fetchMock = stubFetch({
      '/api/business/settings': S, '/api/business/rules': RULES, '/api/accounts': ACCOUNTS, 'PUT /api/business/settings': S,
      'POST /api/business/rules': { rule: { id: 9, kind: 'account', label: 'Rewards Card', account_id: 2, account_name: 'Rewards Card', pct: 20, line: null }, also_tagged: 14 },
    });
    wrapBook(<BusinessSettings />, {}, '/b/ours/settings/business');
    fireEvent.change(await screen.findByLabelText('Business miles, Jul 1 to Dec 31 (76¢ a mile)'), { target: { value: '1000' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save miles' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/business/settings')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PUT', '/api/business/settings')[0].body).toEqual({ year: 2026, car_method: 'standard', miles: [1200, 1000] });
    fireEvent.change(screen.getByLabelText('Account'), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('Business share of everything in it'), { target: { value: '20' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add rule' }));
    expect(await screen.findByText('Tagged 14 earlier transactions too.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/business/rules')[0].body).toEqual({ kind: 'account', account_id: 2, pct: 20, line: null });
  });

  it('a new rule refreshes Spending, the strip on Home and the plan too (final review M4)', async () => {
    stubFetch({
      '/api/business/settings': S, '/api/business/rules': RULES, '/api/accounts': ACCOUNTS,
      'POST /api/business/rules': { rule: { id: 9, kind: 'account', label: 'Rewards Card', account_id: 2, account_name: 'Rewards Card', pct: 20, line: null }, also_tagged: 0 },
    });
    const { qc } = wrapBook(<BusinessSettings />, {}, '/b/ours/settings/business');
    const spy = vi.spyOn(qc, 'invalidateQueries');
    await screen.findByRole('option', { name: 'Rewards Card' });
    fireEvent.change(screen.getByLabelText('Account'), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add rule' }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['spending'] }));   // Spending and Home's strip
    expect(spy).toHaveBeenCalledWith({ queryKey: ['plan'] });
  });

  it('saves who runs the business and refreshes Next dollar (final review ruling I2)', async () => {
    const fetchMock = stubFetch({ '/api/business/settings': S, '/api/business/rules': RULES, '/api/accounts': ACCOUNTS,
      'PUT /api/business/settings': { ...S, owner: 'spouse' } });
    const { qc } = wrapBook(<BusinessSettings />, {}, '/b/ours/settings/business');
    const spy = vi.spyOn(qc, 'invalidateQueries');
    const group = await screen.findByRole('radiogroup', { name: 'Who runs the business' });
    expect(group).toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: 'Sam' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/business/settings')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PUT', '/api/business/settings')[0].body).toEqual({ owner: 'spouse' });
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['next-dollar'] }));
  });

  it('asks who runs the business only when there are two adults', async () => {
    stubFetch({ '/api/business/settings': { ...S, adults: [{ key: 'jr', name: 'JR' }] }, '/api/business/rules': RULES, '/api/accounts': ACCOUNTS });
    wrapBook(<BusinessSettings />, {}, '/b/ours/settings/business');
    await screen.findByRole('radiogroup', { name: 'Business type' });
    expect(screen.queryByRole('radiogroup', { name: 'Who runs the business' })).not.toBeInTheDocument();
  });

  it('switches to last year so it can be finished, and saves that year (final review I2)', async () => {
    const LAST: BusinessSettingsOut = { ...S, year: 2025, home_office: { ...S.home_office, office_sqft: 90 },
      miles: [{ from: '2025-01-01', to: '2025-12-31', rate_tenths: 700, miles: 3000 }] };
    const fetchMock = stubFetch({
      '/api/business/settings?year=2025': LAST, '/api/business/settings': S, '/api/business/rules': RULES, '/api/accounts': ACCOUNTS,
      'PUT /api/business/settings': LAST,
    });
    wrapBook(<BusinessSettings />, {}, '/b/ours/settings/business');
    fireEvent.click(await screen.findByRole('radio', { name: '2025' }));
    expect(await screen.findByLabelText('Business miles, Jan 1 to Dec 31 (70¢ a mile)')).toHaveValue('3000');
    expect(screen.getByLabelText('Office, square feet')).toHaveValue('90');
    fireEvent.click(screen.getByRole('button', { name: 'Save miles' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/business/settings')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PUT', '/api/business/settings')[0].body).toEqual({ year: 2025, car_method: 'standard', miles: [3000] });
    expect(callsTo(fetchMock, 'GET', '/api/business/settings')[0].url).toBe('/api/business/settings');
  });

  it('removing a rule asks first and says tagged transactions keep their tags', async () => {
    const fetchMock = stubFetch({ '/api/business/settings': S, '/api/business/rules': RULES, '/api/accounts': ACCOUNTS, 'DELETE /api/business/rules/2': () => new Response(null, { status: 204 }) });
    wrapBook(<BusinessSettings />, {}, '/b/ours/settings/business');
    fireEvent.click(await screen.findByRole('button', { name: 'Remove rule: ACH CLIENT INV is a client' }));
    const ask = screen.getByRole('dialog', { name: 'Remove this rule?' });
    expect(within(ask).getByText('ACH CLIENT INV is a client')).toBeInTheDocument();
    expect(within(ask).getByText("Transactions it already tagged keep their tags. New ones won't be tagged by it.")).toBeInTheDocument();
    expect(callsTo(fetchMock, 'DELETE', '/api/business/rules')).toHaveLength(0);
    fireEvent.click(within(ask).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/business/rules/2')).toHaveLength(1));
  });

  it('after removing a rule, says which and keeps focus on the rules, not the gone row (THO-1)', async () => {
    let rules = RULES;
    stubFetch({ '/api/business/settings': S, '/api/business/rules': () => reply(rules), '/api/accounts': ACCOUNTS,
      'DELETE /api/business/rules/2': () => { rules = { rules: RULES.rules.filter((r) => r.id !== 2) }; return new Response(null, { status: 204 }); } });
    wrapBook(<BusinessSettings />, {}, '/b/ours/settings/business');
    const button = await screen.findByRole('button', { name: 'Remove rule: ACH CLIENT INV is a client' });
    button.focus();
    fireEvent.click(button);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
    await expectRemovalSaid('Removed rule: ACH CLIENT INV is a client.', () => screen.getByRole('heading', { name: 'Rules' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Remove rule: ACH CLIENT INV is a client' })).toBeNull());
    expect(screen.getByRole('heading', { name: 'Rules' })).toHaveFocus();
  });

  it('a double tap on Remove sends one DELETE', async () => {
    let release: (r: Response) => void = () => {};
    const fetchMock = stubFetch({ '/api/business/settings': S, '/api/business/rules': RULES, '/api/accounts': ACCOUNTS,
      'DELETE /api/business/rules/2': () => new Promise<Response>((res) => { release = res; }) });
    wrapBook(<BusinessSettings />, {}, '/b/ours/settings/business');
    fireEvent.click(await screen.findByRole('button', { name: 'Remove rule: ACH CLIENT INV is a client' }));
    const remove = within(screen.getByRole('dialog', { name: 'Remove this rule?' })).getByRole('button', { name: 'Remove' });
    fireEvent.click(remove);
    fireEvent.click(remove);
    expect(remove).toHaveAttribute('aria-busy', 'true');
    release(new Response(null, { status: 204 }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(callsTo(fetchMock, 'DELETE', '/api/business/rules/2')).toHaveLength(1);
  });

  it('is read-only for a viewer', async () => {
    stubFetch({ '/api/business/settings': S, '/api/business/rules': RULES, '/api/accounts': ACCOUNTS });
    wrapBook(<BusinessSettings />, { role: 'viewer' }, '/b/ours/settings/business');
    expect(await screen.findByText('You can see this book but not change it.')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'S-corp' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: /^Remove rule/ })).toBeNull();
  });

  it('lets a viewer look at last year, still read-only (final review N5)', async () => {
    const LAST: BusinessSettingsOut = { ...S, year: 2025, home_office: { ...S.home_office, office_sqft: 90 },
      miles: [{ from: '2025-01-01', to: '2025-12-31', rate_tenths: 700, miles: 3000 }] };
    stubFetch({ '/api/business/settings?year=2025': LAST, '/api/business/settings': S, '/api/business/rules': RULES, '/api/accounts': ACCOUNTS });
    wrapBook(<BusinessSettings />, { role: 'viewer' }, '/b/ours/settings/business');
    const last = await screen.findByRole('radio', { name: '2025' });
    expect(last).not.toBeDisabled();
    fireEvent.click(last);
    expect(await screen.findByLabelText('Business miles, Jan 1 to Dec 31 (70¢ a mile)')).toHaveValue('3000');
    expect(screen.getByLabelText('Office, square feet')).toBeDisabled();
  });
});
