import { fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, reply, stubFetch, wrapBook } from '../../test-utils';
import { Dismissed } from './Dismissed';

afterEach(() => vi.unstubAllGlobals());

describe('Dismissed suggestions', () => {
  it("lists Not Margaret's answers and suggests one again", async () => {
    const fetchMock = stubFetch({
      '/api/inventory/suggestions/dismissed': { dismissed: [{ id: 3, payer: 'Harbor Savings Bank', kind_label: 'Account', answered_on: '2026-10-16', answered_by: 'Jr' }] },
      'POST /api/inventory/suggestions/3/undo': () => reply({ ok: true }),
    });
    wrapBook(<Dismissed />, { slug: 'margaret-ellis', kind: 'parent', owners: [{ key: 'margaret', label: 'Margaret' }] }, '/b/margaret-ellis/settings/dismissed');
    expect(await screen.findByText('Harbor Savings Bank')).toBeInTheDocument();
    expect(screen.getByText(/Payers answered Not Margaret's/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Suggest again' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/inventory/suggestions/3/undo')).toHaveLength(1));
  });
  it('does not print dangling separators when the date and person are missing', async () => {
    stubFetch({ '/api/inventory/suggestions/dismissed': { dismissed: [{ id: 4, payer: 'Lakeside Funds', kind_label: 'Account', answered_on: null, answered_by: null }] } });
    wrapBook(<Dismissed />, { slug: 'margaret-ellis', kind: 'parent', owners: [{ key: 'margaret', label: 'Margaret' }] }, '/b/margaret-ellis/settings/dismissed');
    await screen.findByText('Lakeside Funds');
    expect(screen.getByText('Account')).toBeInTheDocument();
  });
});
