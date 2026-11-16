import { screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { stubFetch, wrap, wrapBook } from '../../test-utils';
import type { SetupItem } from './api';
import { Setup, orderSetup, rowHref } from './Setup';

afterEach(() => vi.unstubAllGlobals());

const item = (key: SetupItem['key'], title: string, done: boolean, required = true, detail = `${title} detail`, suggested_cents: number | null = null): SetupItem =>
  ({ key, title, done, required, detail, suggested_cents });
const items: SetupItem[] = [
  item('household', 'About you', true),
  item('pay', 'Pay', false),
  item('earnings', 'Earnings record', false),
  item('earnings_spouse', "Sam's earnings record", false, false, 'Optional. Without it, Sam receives the spousal benefit only.'),
  item('children', 'Children', false, true, 'Say which child 529 — kid 2 belongs to.'),
  item('mortgage', 'Mortgage payment', false),
  item('health', 'Health insurance before Medicare', false, true, 'A yearly premium for the household until Medicare.', 1680000),
  item('history', 'Spending history', true),
];
const names = { jr: 'JR', spouse: 'Sam', joint: 'Joint' };

describe('orderSetup (onboarding ruling 10)', () => {
  it('follows the Set up Steward order and keeps the optional record apart', () => {
    const { required, optional } = orderSetup(items);
    expect(required.map((i) => i.key)).toEqual(['household', 'mortgage', 'pay', 'children', 'health', 'earnings', 'history']);
    expect(optional.map((i) => i.key)).toEqual(['earnings_spouse']);
  });
  it('links each item to the setup step that answers it, returning to the Plan', () => {
    expect(rowHref('household')).toBe('/profile/you?from=plan');
    expect(rowHref('pay')).toBe('/profile/you?from=plan');
    expect(rowHref('children')).toBe('/profile/kids?from=plan');
    expect(rowHref('health')).toBe('/profile/benefits?from=plan');
    expect(rowHref('earnings')).toBe('/profile/benefits?from=plan');
    expect(rowHref('mortgage')).toBe('/profile/home?from=plan');
    expect(rowHref('earnings_spouse')).toBe('/profile/benefits?from=plan');
    expect(rowHref('history')).toBe('/settings/import');
  });
});

describe('Setup checklist', () => {
  it('shows progress, rows in order with one-word actions linking into setup, and the untyped notice', async () => {
    stubFetch({
      '/api/plan/setup': { ready: false, setup: items, names },
      '/api/accounts': { accounts: [{ id: 9, name: 'Acct 9999', type: 'unknown', owner: 'joint', source: 'simplefin', institution: 'Big Bank', is_active: true, balance_cents: 0, as_of: null, stale_days: null }] },
      '/api/children': { children: [{ id: 1, label: 'Oldest', birth_year: 2015, cost_level: 'in_state_public', account_id: 11, monthly_contribution_cents: 0 }] },
    });
    wrap(<Setup />, '/plan');
    expect(await screen.findByText('2 of 7 done')).toBeInTheDocument();
    const rows = within(screen.getByRole('region', { name: 'Required' })).getAllByTestId('setup-row');
    expect(rows.map((r) => r.querySelector('.setup__title')!.firstChild!.textContent)).toEqual(
      ['About you', 'Mortgage payment', 'Pay', 'Children', 'Health insurance before Medicare', 'Earnings record', 'Spending history']);
    expect(rows.map((r) => r.querySelector('.setup__go')!.textContent)).toEqual(['Done', 'Add', 'Add', 'Finish', 'Check', 'Upload', 'Done']);
    expect(rows[4]).toHaveTextContent('An estimate is filled in for you to check.');
    expect(within(rows[6]).getByText('Automatic')).toBeInTheDocument();
    expect(rows.map((r) => r.getAttribute('href'))).toEqual([
      '/b/ours/profile/you?from=plan', '/b/ours/profile/home?from=plan', '/b/ours/profile/you?from=plan', '/b/ours/profile/kids?from=plan',
      '/b/ours/profile/benefits?from=plan', '/b/ours/profile/benefits?from=plan', '/b/ours/settings/import',
    ]);
    const optional = within(screen.getByRole('region', { name: 'Optional' })).getByTestId('setup-row');
    expect(optional).toHaveAttribute('href', '/b/ours/profile/benefits?from=plan');
    expect(optional).toHaveTextContent("Sam's earnings record");
    expect(screen.getByText('Accounts without a type')).toBeInTheDocument();
  });

  it('gives a viewer the checklist to read, with no links into setup or import, which only a manager has', async () => {
    stubFetch({ '/api/plan/setup': { ready: false, setup: items, names }, '/api/accounts': { accounts: [] }, '/api/children': { children: [] } });
    wrapBook(<Setup />, { role: 'viewer' }, '/b/ours/plan');
    expect(await screen.findByText('2 of 7 done')).toBeInTheDocument();
    expect(screen.getByText('A manager of this book fills these in. The plan shows no ages until every required item is done.')).toBeInTheDocument();
    const rows = within(screen.getByRole('region', { name: 'Required' })).getAllByTestId('setup-row');
    expect(rows).toHaveLength(7);
    expect(rows.map((r) => r.querySelector('.setup__go')?.textContent ?? '')).toEqual(['Done', '', '', '', '', '', 'Done']);
    // A row with no action word still says its state in words; the empty circle is hidden from a screen reader.
    // A done row's "Done" is already said once.
    expect(rows.map((r) => r.querySelector('.setup__status')?.textContent ?? '')).toEqual(['', 'To do', 'To do', 'To do', 'To do', 'To do', '']);
    expect(screen.queryByRole('link')).toBeNull();
  });
});
