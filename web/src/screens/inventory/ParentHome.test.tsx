import { screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { stubFetch, wrapBook } from '../../test-utils';
import type { Overview } from './api';
import { ParentHome } from './ParentHome';

afterEach(() => vi.unstubAllGlobals());
const PARENT = { slug: 'margaret-ellis', name: 'Margaret Ellis', kind: 'parent' as const, owners: [{ key: 'margaret', label: 'Margaret' }, { key: 'joint', label: 'Joint' }] };
const OV: Overview = {
  net_worth_cents: 118046225, counted_line: "From 7 of Margaret's 8 accounts. The Westmark Life annuity has no balance yet.",
  fresh_line: 'Bank feed updated today, 6:10 AM · statements through Sep 30',
  needs_checking: { count: 2, labels: ['Westmark Life annuity', 'Evergreen Mutual long-term care'] },
  suggestions: { count: 3, found_in: 'found in Margaret’s transactions' },
  totals: [{ key: 'cash', label: 'Cash', cents: 7069465, note: '3 accounts' }, { key: 'debts', label: 'Debts', cents: -118240, note: '1 credit card' }],
  incoming: { monthly_cents: 352500, rows: [{ item_id: 10, name: 'Social Security', cents: 214000, per: 'monthly', sub: 'Around the 3rd · into Wells Fargo ••4417 · after Medicare Part B', status: 'confirmed' }], foot: "Not counted yet: Westmark Life deposits of $410.00 a month, waiting in Is this one of Margaret's?" },
  outgoing: { monthly_cents: 37207, rows: [{ item_id: 12, name: 'Long-term care · Evergreen Mutual', cents: 21200, per: 'monthly', sub: 'Around the 10th · from Wells Fargo ••4417', status: 'needs_checking' }], foot: 'From insurance items. Medicare Part B ($185.00) comes out of Social Security before it arrives.' },
  recent: [{ id: 'c1', at: '2026-10-17T03:51:00+00:00', who: 'Robin', icon: 'pencil', text: 'edited {item}', item: { id: 14, label: 'Homeowners' }, diffs: [], lines: [], note: null, summary: 'Robin edited Homeowners: renewal date, paid from' }],
};
const SUMMARY = {
  '/api/summary': { net_worth_cents: 0, needs_attention: [] },
  '/api/flags': { show: 'open', flags: [], counts: { open: 0, done: 0 }, checks: [], accounts: [], next_offset: null, ran: null, mail_ready: true, can_edit: true },
};

describe('Parent Home', () => {
  it('reads like the mockup', async () => {
    stubFetch({ '/api/inventory/overview': OV, ...SUMMARY });
    wrapBook(<ParentHome />, PARENT, '/b/margaret-ellis');
    expect(await screen.findByText('Net worth, known items')).toBeInTheDocument();
    expect(await screen.findByText('Nothing to look into')).toBeInTheDocument();
    expect(within(screen.getByTestId('net-worth')).getByText('$1,180,462.25')).toBeInTheDocument();
    expect(screen.getByText(OV.counted_line)).toBeInTheDocument();
    expect(screen.getByText('Needs checking: 2')).toBeInTheDocument();
    expect(screen.getByText("Is this one of Margaret's? 3")).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /See them/ })).toHaveAttribute('href', '/b/margaret-ellis/inventory?status=needs_checking');
    expect(screen.getByRole('link', { name: /Go through them/ })).toHaveAttribute('href', '/b/margaret-ellis/inventory/suggestions');
    const has = screen.getByRole('region', { name: 'What Margaret has' });
    expect(within(has).getByText('$70,694.65')).toBeInTheDocument();
    expect(within(has).getByText('−$1,182.40')).toBeInTheDocument();
    expect(screen.getByText('$3,525.00')).toBeInTheDocument();
    expect(screen.getByText(OV.outgoing.foot)).toBeInTheDocument();
    expect(screen.getByText('Robin edited Homeowners: renewal date, paid from')).toBeInTheDocument();
  });
  it('a viewer gets no suggestions card', async () => {
    stubFetch({ '/api/inventory/overview': { ...OV, suggestions: null, incoming: { ...OV.incoming, foot: null } }, ...SUMMARY });
    wrapBook(<ParentHome />, { ...PARENT, role: 'viewer' }, '/b/margaret-ellis');
    expect(await screen.findByText('Needs checking: 2')).toBeInTheDocument();
    expect(screen.queryByText(/Is this one of/)).toBeNull();
  });
  it('still shows the line after an invite is accepted', async () => {
    stubFetch({ '/api/inventory/overview': OV, ...SUMMARY });
    wrapBook(<ParentHome />, PARENT, { pathname: '/b/margaret-ellis', state: { joined: "Mom (Robin's)" } });
    expect(await screen.findByText("You've joined Mom (Robin's).")).toBeInTheDocument();
  });
});
