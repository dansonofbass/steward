import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Account } from '../../api/types';
import { wrapBook } from '../../test-utils';
import { TaxTreatment } from './TaxTreatment';

const acct = (id: number, type: Account['type']): Account => ({
  id, name: `Acct ${id}`, type, owner: 'joint', source: 'simplefin', institution: 'Big Bank', is_active: true,
  balance_cents: 1000, as_of: '2026-10-13', stale_days: 1,
});

describe('the tax mix', () => {
  it('links a manager to Banks to type a new account, and gives a viewer the row without the link', () => {
    const { unmount } = wrapBook(<TaxTreatment accounts={[acct(1, 'unknown'), acct(2, 'checking')]} />);
    expect(screen.getByRole('link', { name: /type/ })).toHaveAttribute('href', '/b/ours/settings/banks');
    unmount();
    wrapBook(<TaxTreatment accounts={[acct(1, 'unknown'), acct(2, 'checking')]} />, { role: 'viewer' });
    expect(screen.getByText(/1 new account/)).toBeInTheDocument();
    expect(screen.queryByRole('link')).toBeNull();
  });
});
