import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { wrapBook } from '../test-utils';
import type { Account } from '../api/types';
import { UntypedNotice, untypedCopy, untypedCount } from './UntypedNotice';

const acct = (id: number, type: Account['type'], is_active = true): Account => ({
  id, name: `Acct ${id}`, type, owner: 'joint', source: 'simplefin', institution: 'Big Bank', is_active,
  balance_cents: 1000, as_of: '2026-10-13', stale_days: 1,
});

describe('untyped accounts', () => {
  it('counts only active accounts without a type', () => {
    expect(untypedCount([acct(1, 'unknown'), acct(2, 'unknown', false), acct(3, 'checking')])).toBe(1);
    expect(untypedCount(undefined)).toBe(0);
  });

  it('words one and many for each place', () => {
    expect(untypedCopy(1, 'spending')).toEqual({
      eyebrow: 'Accounts without a type', link: 'Set the type of 1 new account',
      body: '1 new account has no type. It is not included here or in the plan.',
    });
    expect(untypedCopy(2, 'plan').body).toBe(
      '2 new accounts have no type. Until they have one, they are not included in spending or savings, and the plan is less accurate.');
    expect(untypedCopy(2, 'plan').eyebrow).toBe('Accounts without a type');
  });

  it('links to the New accounts editor, and shows nothing when every account has a type', () => {
    const { rerender } = render(<MemoryRouter><UntypedNotice accounts={[acct(1, 'unknown'), acct(2, 'unknown')]} where="spending" /></MemoryRouter>);
    expect(screen.getByRole('link', { name: 'Set the type of 2 new accounts' })).toHaveAttribute('href', '/b/ours/settings/banks');
    rerender(<MemoryRouter><UntypedNotice accounts={[acct(3, 'checking')]} where="spending" /></MemoryRouter>);
    expect(screen.queryByRole('status')).toBeNull();
  });

  it("gives a viewer the notice without the link to Banks, which only a manager has", () => {
    wrapBook(<UntypedNotice accounts={[acct(1, 'unknown')]} where="spending" />, { role: 'viewer' });
    expect(screen.getByText('1 new account has no type. It is not included here or in the plan.')).toBeInTheDocument();
    expect(screen.queryByRole('link')).toBeNull();
  });
});
