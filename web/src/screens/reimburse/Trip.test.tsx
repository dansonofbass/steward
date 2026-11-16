import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { callsTo, renderAt, stubFetch } from '../../test-utils';
import { TRIP_DETAIL } from './fixtures';
import { TripPage } from './Trip';

beforeEach(() => { localStorage.clear(); localStorage.setItem('steward-celebrations', 'off'); });
afterEach(() => vi.unstubAllGlobals());
const ACME = { payers: [{ id: 1, name: 'Acme' }] };
const page = (book = {}) => renderAt(
  <Routes><Route path="/b/ours/spending/reimbursements/trips/:id" element={<TripPage />} /></Routes>, book, '/spending/reimbursements/trips/5');
const rowOf = (raw: string) => screen.getAllByTestId('trip-row').find((r) => r.textContent?.includes(raw))!;
const mark = () => screen.getByRole('button', { name: /^Mark \d+ reimbursable · / });

describe("a trip's review list (reimbursable spec, The review list)", () => {
  it('shows the groups in order, each row with why, ticked as the server says, and the button counts the ticked', async () => {
    stubFetch({ '/api/reimburse/trips/5': TRIP_DETAIL, '/api/reimburse/payers': ACME });
    page();
    expect(await screen.findByRole('heading', { level: 1, name: 'Chicago trip' })).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent))
      .toEqual(['Booked before the trip', 'Likely work', 'Probably home', 'Not sure']);
    expect(rowOf('UNITED AIRLINES')).toHaveTextContent('booked ahead');
    expect(rowOf('PORTILLOS')).toHaveTextContent('says Chicago');
    expect(rowOf('KROGER')).toHaveTextContent('a regular near home');
    expect(rowOf('DAYCARE')).toHaveTextContent('Childcare and school');
    expect(rowOf('CORNER MART')).toHaveTextContent('no clue either way');
    expect(within(rowOf('KROGER')).getByRole('checkbox')).not.toBeChecked();
    expect(mark()).toHaveTextContent('Mark 4 reimbursable · $1,116.20');
  });

  it('unticking changes the count, and Mark sends the ticked in one request with Undo after', async () => {
    const fetchMock = stubFetch({
      '/api/reimburse/trips/5': TRIP_DETAIL, '/api/reimburse/payers': ACME,
      'POST /api/reimburse/trips/5/mark': { count: 3, total_cents: 108780, payer: 'Acme', owed_cents: 124035, undo: 'tok',
        trip: { ...TRIP_DETAIL.trip, count: 3, total_cents: 108780, status: 'waiting' } },
      'POST /api/undo/tok': { undone: 3, transaction: null },
    });
    page();
    await screen.findAllByTestId('trip-row');
    fireEvent.click(within(rowOf('UBER TRIP')).getByRole('checkbox'));
    expect(mark()).toHaveTextContent('Mark 3 reimbursable · $1,087.80');
    fireEvent.click(mark());
    expect(await screen.findByText('Chicago trip: 3 charges, $1,087.80, reimbursable. Acme owes you $1,240.35.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/reimburse/trips/5/mark')[0].body).toEqual({ ids: [1, 2, 4] });
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(await screen.findByText('Undone.')).toBeInTheDocument();
  });

  it('Not reimbursed on a reimbursable row says it counts as spending again', async () => {
    const fetchMock = stubFetch({
      '/api/reimburse/trips/5': TRIP_DETAIL, '/api/reimburse/payers': ACME,
      'PATCH /api/transactions/3': { ...TRIP_DETAIL.rows[2], reimburser_id: null, trip_id: null, result: { category: 'transport', applied: 0,
        rule: 'none', undo: 'tok', reimburse: { change: 'unmarked', reimburser_id: 1, payer: 'Acme', was_cents: 2840, owed_cents: 0 } } },
    });
    page();
    await screen.findAllByTestId('trip-row');
    expect(within(rowOf('PALMER HOUSE')).queryByRole('button', { name: /^Not reimbursed/ })).toBeNull();
    fireEvent.click(within(rowOf('UBER TRIP')).getByRole('button', { name: 'Not reimbursed: UBER TRIP' }));
    expect(await screen.findByText('Not reimbursed: $28.40 counts as your spending again.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/3')[0].body).toEqual({ reimbursable: false });
  });

  it('Edit changes the dates in one PATCH', async () => {
    const fetchMock = stubFetch({
      '/api/reimburse/trips/5': TRIP_DETAIL, '/api/reimburse/payers': ACME,
      'PATCH /api/reimburse/trips/5': { trip: { ...TRIP_DETAIL.trip, end: '2026-10-10' } },
    });
    page();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const sheet = screen.getByRole('dialog', { name: 'Edit the trip' });
    fireEvent.change(within(sheet).getByLabelText('End'), { target: { value: '2026-10-10' } });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/reimburse/trips/5')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PATCH', '/api/reimburse/trips/5')[0].body).toEqual(
      { name: 'Chicago trip', start: '2026-10-06', end: '2026-10-10', city: 'Chicago, IL' });
  });

  it('a viewer sees the list and changes nothing', async () => {
    stubFetch({ '/api/reimburse/trips/5': TRIP_DETAIL, '/api/reimburse/payers': ACME });
    page({ role: 'viewer' });
    await screen.findAllByTestId('trip-row');
    for (const box of screen.getAllByRole('checkbox')) expect(box).toBeDisabled();
    expect(screen.queryByRole('button', { name: /^Mark / })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
  });
});
