import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { stubFetch, wrap, wrapBook } from '../test-utils';
import { AddAccountSheet } from './accounts/ManualAccounts';
import { ParentHome } from './inventory/ParentHome';
import Reset from './Reset';
import Review from './Review';
import Members from './settings/Members';

afterEach(() => vi.unstubAllGlobals());
const TXN = { id: 7, account_id: 1, account_name: 'Checking', posted_at: '2026-10-10', amount_cents: -1200, raw_description: 'SQ *VENDOR', merchant: null, category: 'uncategorized', is_business: false, is_transfer: false, business_pct: 0, business_line: null, business_source: 'none', category_source: 'none', reviewed_at: null, from_bank: true };
const REVIEW = { uncategorized: [TXN], count: 1, duplicates: [], duplicate_count: 0, top_categories: ['groceries'], business: [], business_count: 0 };
const ME = { user: { id: 1, username: 'jr', display_name: 'JR' }, session: { id: 9, device_label: 'Phone', created_at: '2026-10-01T00:00:00Z' }, books: [] };

describe('books in the screens', () => {
  it('a viewer sees Review with its controls disabled and the plain line', async () => {
    stubFetch({ '/api/review': REVIEW });
    wrapBook(<Review />, { role: 'viewer' });
    expect(await screen.findByText('You can see this book but not change it.')).toBeInTheDocument();
    const buttons = screen.getAllByRole('button');
    expect(buttons.length).toBeGreaterThan(0);
    buttons.forEach((b) => expect(b).toBeDisabled());
  });
  it('a manager sees Review as before', async () => {
    stubFetch({ '/api/review': REVIEW });
    wrapBook(<Review />);
    expect(await screen.findByTestId('review-top')).toHaveTextContent('1 left');
    expect(screen.queryByText('You can see this book but not change it.')).toBeNull();
  });
  it('the account form offers the book\'s own owners', () => {
    wrapBook(<AddAccountSheet onClose={() => {}} onSaved={() => {}} />, { slug: 'mom', kind: 'parent', owners: [{ key: 'margaret', label: 'Margaret' }, { key: 'joint', label: 'Joint' }] }, '/b/mom/settings/banks');
    const owner = screen.getByLabelText('Owner') as HTMLSelectElement;
    expect([...owner.options].map((o) => o.textContent)).toEqual(['Margaret', 'Joint']);
    expect(owner.value).toBe('joint');
  });
  it('Book members offers a reset only where the server allows it', async () => {
    stubFetch({ '/api/auth/me': ME, '/api/books/mom/members': { members: [] }, '/api/users': { users: [
      { id: 1, username: 'jr', display_name: 'JR', email: 'jr@example.com', can_reset: false },
      { id: 2, username: 'sam', display_name: 'Sam', email: 'sam@example.com', can_reset: true },
      { id: 3, username: 'vee', display_name: 'Vee', email: 'vee@example.com', can_reset: false }] } });
    wrapBook(<Members />, { slug: 'mom', kind: 'parent' }, '/b/mom/settings/members');
    expect(await screen.findByRole('button', { name: "Reset Sam's password" })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: "Reset Vee's password" })).toBeNull();
  });
  it('a parent book\'s Home shows the line after an invite is accepted', async () => {
    stubFetch({ '/api/summary': { net_worth_cents: 0, needs_attention: [] }, '/api/inventory/overview': { net_worth_cents: 0, counted_line: '', fresh_line: null, needs_checking: { count: 0, labels: [] }, suggestions: null, totals: [], incoming: { monthly_cents: 0, rows: [], foot: null }, outgoing: { monthly_cents: 0, rows: [], foot: '' }, recent: [] } });
    wrapBook(<ParentHome />,{ slug: 'mom', kind: 'parent' }, { pathname: '/b/mom', state: { joined: "Mom (Robin's)" } });
    expect(await screen.findByText("You've joined Mom (Robin's).")).toBeInTheDocument();
  });
  it('a reset link says up front what a new password clears', () => {
    wrap(<Reset />, '/reset?token=abc');
    expect(screen.getByRole('heading', { name: 'Change password' })).toBeInTheDocument();
    expect(screen.getByText('Choose a new password. This signs you out everywhere, removes your passkeys and ends any Claude Code grants.')).toBeInTheDocument();
  });
  it('an invite link asks the person to choose a password', () => {
    wrap(<Reset />, '/reset?token=abc&invite=1');
    expect(screen.getByRole('heading', { name: 'Choose your password' })).toBeInTheDocument();
    expect(screen.getByText('Choose a password to finish setting up your sign-in.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Choose your password' })).toBeInTheDocument();
  });
});
