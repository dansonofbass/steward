import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as celebrate from '../../celebrate/celebrate';
import { callsTo, reply, renderAt, stubFetch } from '../../test-utils';
import { ACME, EMPTY_SUMMARY, GLOBEX, SUMMARY } from './fixtures';
import { Reimbursements } from './Reimbursements';

beforeEach(() => { localStorage.clear(); localStorage.setItem('steward-celebrations', 'off'); });
afterEach(() => vi.unstubAllGlobals());
const page = (path = '/spending/reimbursements') => renderAt(<Reimbursements />, {}, path);

describe('the Reimbursements tab (reimbursable spec, Where they live)', () => {
  it('with no payer yet, says what it is for and offers a trip', async () => {
    stubFetch({ '/api/reimburse': EMPTY_SUMMARY });
    page();
    expect(await screen.findByText("Work travel you'll be paid back for stays out of your spending here. Mark a charge Reimbursable, or add a trip.")).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add a trip' })).toBeInTheDocument();
    expect(screen.queryByText('Owed to you')).toBeNull();
    expect(within(screen.getByRole('navigation', { name: 'Spending views' })).getByRole('link', { name: 'Reimbursements' }))
      .toHaveAttribute('aria-current', 'page');
  });

  it('shows what Acme owes, the trips newest first with their status, and the single charges', async () => {
    stubFetch({ '/api/reimburse': SUMMARY });
    page();
    expect(await screen.findByText('Acme owes you $1,240.35')).toBeInTheDocument();
    expect(screen.getByText('$2,030 marked since Sep 1 · $790 paid back · last repayment Oct 15')).toBeInTheDocument();
    const trips = screen.getAllByTestId('rb-trip');
    expect(trips.map((t) => t.querySelector('.rb-item__name')!.textContent)).toEqual(['Austin trip', 'Chicago trip']);
    expect(trips[0]).toHaveTextContent('Oct 20 – Oct 22 · 4 charges · waiting');
    expect(trips[1]).toHaveTextContent('paid back ✓');
    expect(trips[0]).toHaveAttribute('href', '/b/ours/spending/reimbursements/trips/6');
    expect(screen.getByRole('heading', { name: 'Trips' }).querySelector('svg')).not.toBeNull();   // the paper plane
    expect(screen.getByTestId('rb-single')).toHaveTextContent('Taxi');
    expect(screen.getByTestId('rb-single')).toHaveTextContent('$18.40');
  });

  it('with two payers, one block each', async () => {
    stubFetch({ '/api/reimburse': { ...SUMMARY, payers: [ACME, GLOBEX] } });
    page();
    await screen.findByText('Acme owes you $1,240.35');
    expect(screen.getAllByTestId('rb-owed').map((b) => b.querySelector('.rb-owed__big')!.textContent))
      .toEqual(['Acme owes you $1,240.35', 'Globex owes you $60.35']);
  });

  it('a balance below $0 says so and links to likely unmarked travel', async () => {
    stubFetch({ '/api/reimburse': { ...SUMMARY, payers: [{ ...ACME, owed_cents: -4000 }] } });
    page();
    expect(await screen.findByText("Acme has paid you $40.00 more than you've marked. A charge may not be marked yet.")).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Travel from the last 90 days' }))
      .toHaveAttribute('href', '/b/ours/transactions?category=travel&dates=custom&from=2026-07-30');
    expect(screen.queryByRole('button', { name: 'Settle' })).toBeNull();
  });

  it('Settle: the sheet says what happens, defaults the category, settles, cheers, and undoes', async () => {
    const fetchMock = stubFetch({
      '/api/reimburse': { ...SUMMARY, payers: [{ ...ACME, owed_cents: 6035 }] },
      'POST /api/reimburse/payers/1/settle': { owed_cents: 0, settled_cents: 6035, category: 'dining', month: '2026-10', undo: 'tok' },
      'POST /api/undo/tok': { undone: 0, transaction: null },
    });
    page();
    fireEvent.click(await screen.findByRole('button', { name: 'Settle' }));
    const sheet = screen.getByRole('dialog', { name: 'Settle' });
    expect(sheet).toHaveTextContent('Settle the $60.35 Acme still owes you as not coming back? It counts as your spending in October 2026.');
    const pick = within(sheet).getByLabelText('Counts as') as HTMLSelectElement;
    expect(pick.value).toBe('travel');
    fireEvent.change(pick, { target: { value: 'dining' } });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Settle' }));
    expect(await screen.findByText('All square with Acme.')).toBeInTheDocument();
    expect(screen.getByText((_, el) => !!el?.matches('.rb-said p') && el.textContent === 'Settled: $60.35 counts as Eating out in October 2026.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/reimburse/payers/1/settle')[0].body).toEqual({ amount_cents: 6035, category: 'dining' });
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(await screen.findByText('Undone.')).toBeInTheDocument();
  });

  async function settleOnce() {
    stubFetch({
      '/api/reimburse': { ...SUMMARY, payers: [{ ...ACME, owed_cents: 6035 }] },
      'POST /api/reimburse/payers/1/settle': { owed_cents: 0, settled_cents: 6035, category: 'travel', month: '2026-10', undo: 'tok' },
    });
    page();
    fireEvent.click(await screen.findByRole('button', { name: 'Settle' }));
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Settle' })).getByRole('button', { name: 'Settle' }));
    expect(await screen.findByText('All square with Acme.')).toBeInTheDocument();
  }
  const motion = (reduce: boolean) => vi.stubGlobal('matchMedia', (q: string) => ({
    matches: reduce && q === '(prefers-reduced-motion: reduce)', media: q, addEventListener: () => {}, removeEventListener: () => {} }));

  it('with reduced motion the cheer still says all square and the square animation never starts', async () => {
    localStorage.removeItem('steward-celebrations');
    motion(true);
    const square = vi.spyOn(celebrate, 'square');
    await settleOnce();
    await new Promise((r) => { setTimeout(r, 50); });
    expect(square).not.toHaveBeenCalled();
    expect(document.querySelector('.cel-moment')).toBeNull();
  });

  it('without reduced motion the same settle does start the square animation (the harness can see it)', async () => {
    localStorage.removeItem('steward-celebrations');
    motion(false);
    const square = vi.spyOn(celebrate, 'square');
    await settleOnce();
    await waitFor(() => expect(square).toHaveBeenCalledTimes(1));
  });

  it("a repayment's Settle link opens the sheet", async () => {
    stubFetch({ '/api/reimburse': { ...SUMMARY, payers: [{ ...ACME, owed_cents: 6035 }] } });
    page('/spending/reimbursements?settle=1');
    expect(await screen.findByRole('dialog', { name: 'Settle' })).toBeInTheDocument();
  });

  it('Add a trip: the city names it, Save makes it and opens its list', async () => {
    const fetchMock = stubFetch({
      '/api/reimburse': SUMMARY, '/api/reimburse/payers': { payers: [{ id: 1, name: 'Acme' }] },
      'POST /api/reimburse/trips': () => reply({ trip: { ...SUMMARY.trips[1], id: 7 } }, 201),
    });
    const { location } = page();
    fireEvent.click((await screen.findAllByRole('button', { name: 'Add a trip' }))[0]);
    const sheet = screen.getByRole('dialog', { name: 'Add a trip' });
    fireEvent.change(within(sheet).getByLabelText('Start'), { target: { value: '2026-10-06' } });
    fireEvent.change(within(sheet).getByLabelText('End'), { target: { value: '2026-10-09' } });
    fireEvent.change(within(sheet).getByLabelText('City (optional)'), { target: { value: 'Chicago, IL' } });
    expect(within(sheet).getByLabelText('Name')).toHaveValue('Chicago trip');
    fireEvent.click(within(sheet).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(location.current.pathname).toBe('/b/ours/spending/reimbursements/trips/7'));
    expect(callsTo(fetchMock, 'POST', '/api/reimburse/trips')[0].body).toEqual(
      { name: 'Chicago trip', start: '2026-10-06', end: '2026-10-09', city: 'Chicago, IL' });
  });

  it('Add a trip with no payer yet asks who pays you back first', async () => {
    const fetchMock = stubFetch({
      '/api/reimburse': EMPTY_SUMMARY,
      'POST /api/reimburse/payers': () => reply({ id: 1, name: 'Acme' }, 201),
      'POST /api/reimburse/trips': () => reply({ trip: { ...SUMMARY.trips[1], id: 7 } }, 201),
    });
    page();
    fireEvent.click(await screen.findByRole('button', { name: 'Add a trip' }));
    const sheet = screen.getByRole('dialog', { name: 'Add a trip' });
    fireEvent.change(within(sheet).getByLabelText('Start'), { target: { value: '2026-10-06' } });
    fireEvent.change(within(sheet).getByLabelText('End'), { target: { value: '2026-10-09' } });
    fireEvent.change(within(sheet).getByLabelText('Name'), { target: { value: 'Offsite' } });
    expect(within(sheet).getByRole('button', { name: 'Save' })).toBeDisabled();
    fireEvent.change(within(sheet).getByPlaceholderText('Your employer, e.g. Acme'), { target: { value: 'Acme' } });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/reimburse/trips')).toHaveLength(1));
    expect(callsTo(fetchMock, 'POST', '/api/reimburse/payers')[0].body).toEqual({ name: 'Acme' });
    expect(callsTo(fetchMock, 'POST', '/api/reimburse/trips')[0].body).toEqual(
      { name: 'Offsite', start: '2026-10-06', end: '2026-10-09', city: null, reimburser_id: 1 });
  });
});
