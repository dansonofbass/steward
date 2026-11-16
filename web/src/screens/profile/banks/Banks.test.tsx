import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { stubFetch } from '../../../test-utils';
import { ME, atProfile, profileState } from '../fixtures';

afterEach(() => vi.unstubAllGlobals());

describe('Banks and accounts', () => {
  it('the card lists every account kept by hand with its last update, and Manage banks', async () => {
    stubFetch({ '/api/profile': profileState({ banks: { status: 'done' } }), '/api/auth/me': ME, '/api/simplefin': { linked: true },
      '/api/accounts': { accounts: [
        { id: 1, name: 'Home', type: 'property', owner: 'joint', source: 'manual', institution: 'Manual', is_active: true, balance_cents: 1, as_of: '2026-10-01', stale_days: 12 },
        { id: 2, name: 'Checking', type: 'checking', owner: 'joint', source: 'simplefin', institution: 'Bank', is_active: true, balance_cents: 1, as_of: '2026-10-13', stale_days: 0 },
      ] } });
    atProfile('/profile/banks');
    expect(await screen.findByRole('heading', { name: 'Kept by hand' })).toBeInTheDocument();
    expect(screen.getByText("These don't update themselves. Update a balance from its account; the Plan notes any older than 90 days.")).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Home · Oct 1' })).toHaveAttribute('href', '/b/ours/accounts/1');
    expect(screen.queryByRole('link', { name: /^Checking/ })).toBeNull();
    expect(screen.getByRole('link', { name: 'Manage banks' })).toHaveAttribute('href', '/b/ours/settings/banks');
    expect(screen.getByText('SimpleFIN linked · 2 accounts · all with a type')).toBeInTheDocument();
  });
});
