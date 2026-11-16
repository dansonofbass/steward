import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, reply, stubFetch, wrapBook } from '../../test-utils';
import { BANK_TYPE_OPTIONS } from '../settings/shared';
import { AddAccount } from './AddAccount';

afterEach(() => vi.unstubAllGlobals());

describe('Add an account', () => {
  it('says in one line what each way covers', () => {
    wrapBook(<AddAccount onClose={() => {}} />, {}, '/b/ours/accounts');
    const sheet = screen.getByRole('dialog', { name: 'Add an account' });
    expect(within(sheet).getByRole('link', { name: /Link a bank/ })).toHaveTextContent('Through SimpleFIN; it updates every few hours');
    expect(within(sheet).getByRole('button', { name: /One you update manually/ })).toHaveTextContent("A loan, a car, a house, an account your bank can't connect");
    expect(within(sheet).getByRole('link', { name: /Import files/ })).toHaveTextContent('CSV, OFX or QFX downloads from your bank');
  });

  it('closes when a way that leaves the tab is chosen', () => {
    const onClose = vi.fn();
    wrapBook(<AddAccount onClose={onClose} />, {}, '/b/ours/accounts');
    fireEvent.click(screen.getByRole('link', { name: /Link a bank/ }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('One you update manually adds the account in place and closes once it is saved', async () => {
    const onClose = vi.fn();
    const fetchMock = stubFetch({ 'POST /api/accounts': () => reply({ id: 9 }, 201), '/api/accounts': { accounts: [] } });
    wrapBook(<AddAccount onClose={onClose} />, {}, '/b/ours/accounts');
    fireEvent.click(screen.getByRole('button', { name: /One you update manually/ }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Car' } });
    fireEvent.change(screen.getByLabelText('Balance'), { target: { value: '-12000' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(callsTo(fetchMock, 'POST', '/api/accounts')[0].body).toMatchObject({ name: 'Car', balance_cents: -1200000 });
  });

  it('a vehicle can name the loan against it, and only a vehicle asks (investment views spec)', async () => {
    const onClose = vi.fn();
    const loan = { id: 10, name: 'Car loan', type: 'loan', owner: 'joint', source: 'manual', institution: 'Manual', is_active: true,
      balance_cents: -980000, as_of: '2026-10-01', stale_days: 0 };
    const fetchMock = stubFetch({ 'POST /api/accounts': () => reply({ id: 9 }, 201), '/api/accounts': { accounts: [loan] } });
    wrapBook(<AddAccount onClose={onClose} />, {}, '/b/ours/accounts');
    fireEvent.click(screen.getByRole('button', { name: /One you update manually/ }));
    expect(screen.queryByLabelText('Loan against it')).toBeNull();
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Subaru' } });
    fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'vehicle' } });
    fireEvent.change(await screen.findByLabelText('Loan against it'), { target: { value: '10' } });
    fireEvent.change(screen.getByLabelText('Balance'), { target: { value: '18000' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(callsTo(fetchMock, 'POST', '/api/accounts')[0].body).toMatchObject({ name: 'Subaru', type: 'vehicle', balance_cents: 1800000, loan_id: 10 });
  });

  it('a vehicle balance hint says what it is worth, not to use a negative', () => {
    wrapBook(<AddAccount onClose={() => {}} />, {}, '/b/ours/accounts');
    fireEvent.click(screen.getByRole('button', { name: /One you update manually/ }));
    expect(screen.getByText('For a loan or card, use a negative number.')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'vehicle' } });
    expect(screen.getByText("What it's worth today.")).toBeInTheDocument();
    expect(screen.queryByText('For a loan or card, use a negative number.')).toBeNull();
  });

  it("offers Vehicle for an account entered by hand, never for a bank's", () => {
    expect(BANK_TYPE_OPTIONS.map((o) => o.value)).not.toContain('vehicle');
    expect(BANK_TYPE_OPTIONS).toHaveLength(14);
  });
});
