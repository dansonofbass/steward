import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { HomeData } from '../../api/home';
import { letTestingLibraryDriveFakeTimers, useFakeTimers } from '../../test-clock';
import { callsTo, reply, stubFetch, wrapBook } from '../../test-utils';
import { profileState } from '../profile/fixtures';
import { HOME, homeWith } from './fixtures';
import { ForYou } from './ForYou';

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
const REVIEW = (count: number, background = { pending: 0, done: 0, waiting: false }) => ({ uncategorized: [], count, duplicates: [], duplicate_count: 0, top_categories: [], business: [], business_count: 0, background });
const FINISHED = profileState({ you: { status: 'done' }, kids: { status: 'done' }, home: { status: 'done' }, benefits: { status: 'done' }, banks: { status: 'done' } });
const LATER = '2099-01-01T00:00:00+00:00';
const ROUTES = { '/api/review': REVIEW(0), '/api/taxes/notice': { notice: null }, '/api/profile': FINISHED };
const SYNC = 'Big Bank needs you to sign in again at SimpleFIN';
const ONE_EVENT: HomeData = homeWith({ for_you: [{ kind: 'event', id: 41, event_kind: 'sync', level: 'warn', message: SYNC }] });
const DINING = { category: 'dining', spent_cents: 64_000, target_cents: 50_000, over_cents: 14_000, over_level: 'clear' as const };
const TEN: HomeData = homeWith({
  for_you: [
    { kind: 'event', id: 41, event_kind: 'sync', level: 'warn', message: SYNC },
    { kind: 'event', id: 42, event_kind: 'chat', level: 'error', message: 'A sent answer is missing from the record.' },
    { kind: 'event', id: 43, event_kind: 'mail', level: 'info', message: "An email to Sam couldn't be sent." },
    { kind: 'same_account', n: 1, name: "Nora's 529" },
    { kind: 'untyped', n: 1 },
    { kind: 'owed', payers: [{ name: 'Northwind', cents: 118_400 }], others: { n: 0, cents: 0 } },
  ],
  signs: { ...HOME.signs, flexible: { spent_cents: 314_000, target_cents: 420_000, rows: [DINING] } },
});
const rows = () => screen.getAllByRole('listitem');

describe('For you (Home spec, section 2)', () => {
  it('shows six rows, then "{n} more" shows the rest in place, each row linking where it should', async () => {
    stubFetch({ ...ROUTES, '/api/review': REVIEW(12), '/api/taxes/notice': { notice: { due: '2027-01-15', line: 'Quarterly taxes: $2,400 due Jan 15', federal_cents: 0, state_cents: 0 } },
      '/api/profile': profileState({ you: { status: 'done' } }) });
    wrapBook(<ForYou data={TEN} ready />);
    const more = await screen.findByRole('button', { name: '4 more' });         // Review, tax and Profile have answered
    expect(rows()).toHaveLength(6);
    fireEvent.click(more);
    expect(rows()).toHaveLength(10);
    expect(screen.queryByRole('button', { name: /more$/ })).toBeNull();
    expect(within(rows()[0]).getByRole('link', { name: 'Fix ›' })).toHaveAttribute('href', '/b/ours/settings/banks');
    expect(within(rows()[1]).getByRole('link', { name: 'See ›' })).toHaveAttribute('href', '/b/ours/settings/chat/sent');
    expect(within(rows()[2]).getByRole('link', { name: 'See ›' })).toHaveAttribute('href', '/b/ours/settings/log');
    expect(within(rows()[3]).getByRole('link')).toHaveAttribute('href', '/b/ours/spending/dining?month=2026-10');
    expect(within(rows()[4]).getByRole('link')).toHaveAttribute('href', '/b/ours/accounts');
    expect(within(rows()[5]).getByRole('link')).toHaveAttribute('href', '/b/ours/settings/banks');
    expect(within(rows()[6]).getByRole('link')).toHaveAttribute('href', '/b/ours/review');
    expect(within(rows()[7]).getByRole('link')).toHaveAttribute('href', '/b/ours/spending/reimbursements');
    expect(within(rows()[8]).getByRole('link')).toHaveAttribute('href', '/b/ours/taxes');
    expect(within(rows()[9]).getByRole('link', { name: 'Continue ›' })).toHaveAttribute('href', '/b/ours/profile/kids/kids');
    expect(rows()[0].querySelector('.foryou__dot')).toHaveClass('is-amber');
    expect(rows()[4].querySelector('.foryou__dot')).not.toHaveClass('is-amber');
    expect(rows()[0].querySelector('.foryou__dot')).toHaveAttribute('aria-hidden', 'true');
  });

  it('an import event reads Import › and goes to the Import screen', async () => {
    stubFetch(ROUTES);
    wrapBook(<ForYou data={homeWith({ for_you: [{ kind: 'event', id: 51, event_kind: 'import', level: 'warn', message: 'A statement was cleared after a week.' }] })} ready />);
    expect(await screen.findByRole('link', { name: 'Import ›' })).toHaveAttribute('href', '/b/ours/settings/import');
  });

  it('Dismiss folds the row away, says "Dismissed · Undo" for 10 seconds, and Undo brings it back', async () => {
    useFakeTimers();
    letTestingLibraryDriveFakeTimers();
    const fetchMock = stubFetch({ ...ROUTES, 'POST /api/events/41/resolve': { undo: 'tok' }, 'POST /api/undo/tok': { undone: 0, transaction: null } });
    const { qc } = wrapBook(<ForYou data={ONE_EVENT} ready />);
    const invalidate = vi.spyOn(qc, 'invalidateQueries');
    fireEvent.click(await screen.findByRole('button', { name: `Dismiss: ${SYNC}` }));
    expect(await screen.findByRole('status')).toHaveTextContent('Dismissed · Undo');
    expect(screen.queryByText(SYNC)).toBeNull();
    expect(screen.getByText('Nothing needs you.')).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole('status')).getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/undo/tok')).toHaveLength(1));
    expect(await screen.findByText(SYNC)).toBeInTheDocument();
    expect(invalidate.mock.calls.map(([f]) => JSON.stringify(f?.queryKey))).toEqual(expect.arrayContaining([JSON.stringify(['home']), JSON.stringify(['events'])]));
    fireEvent.click(await screen.findByRole('button', { name: `Dismiss: ${SYNC}` }));
    await screen.findByRole('status');
    act(() => { vi.advanceTimersByTime(10_000); });
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('a failed Undo keeps the toast and says why, and the row stays away', async () => {
    const fetchMock = stubFetch({ ...ROUTES, 'POST /api/events/41/resolve': { undo: 'tok' },
      'POST /api/undo/tok': () => reply({ error: "That changed since, so it can't be undone." }, 409) });
    wrapBook(<ForYou data={ONE_EVENT} ready />);
    fireEvent.click(await screen.findByRole('button', { name: `Dismiss: ${SYNC}` }));
    fireEvent.click(within(await screen.findByRole('status')).getByRole('button', { name: 'Undo' }));
    expect(await screen.findByRole('alert')).toHaveTextContent("That changed since, so it can't be undone.");
    expect(callsTo(fetchMock, 'POST', '/api/undo/tok')).toHaveLength(1);
    expect(within(screen.getByRole('status')).getByRole('button', { name: 'Undo' })).toBeInTheDocument();
    expect(screen.queryByText(SYNC)).toBeNull();
  });

  it('when the focused row leaves, focus goes to the "For you" heading', async () => {
    stubFetch({ ...ROUTES, 'POST /api/events/41/resolve': { undo: 'tok' } });
    wrapBook(<ForYou data={ONE_EVENT} ready />);
    const dismiss = await screen.findByRole('button', { name: `Dismiss: ${SYNC}` });
    dismiss.focus();
    fireEvent.click(dismiss);
    await waitFor(() => expect(screen.getByRole('heading', { level: 2, name: 'For you' })).toHaveFocus());
  });

  it('Later folds the Profile row away with "Hidden for a week · Undo", and Undo brings it back', async () => {
    const fetchMock = stubFetch({ ...ROUTES, '/api/profile': profileState({ you: { status: 'done' } }),
      'POST /api/profile/later': () => reply({ ...profileState({ you: { status: 'done' } }, { later_until: LATER }), undo: 'l' }),
      'POST /api/undo/l': { undone: 0, transaction: null } });
    const { qc } = wrapBook(<ForYou data={HOME} ready />);
    const invalidate = vi.spyOn(qc, 'invalidateQueries');
    const row = await screen.findByTestId('profile-line');
    expect(row).toHaveTextContent('Your profile is 1 of 5 done. Next: Kids and college, about 2 minutes');
    fireEvent.click(within(row).getByRole('button', { name: 'Later' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Hidden for a week · Undo');
    await waitFor(() => expect(screen.queryByTestId('profile-line')).toBeNull());
    expect(callsTo(fetchMock, 'POST', '/api/profile/later')[0].body).toEqual({ later: true });
    fireEvent.click(within(screen.getByRole('status')).getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/undo/l')).toHaveLength(1));
    expect(await screen.findByTestId('profile-line')).toBeInTheDocument();
    expect(invalidate.mock.calls.map(([f]) => JSON.stringify(f?.queryKey))).toEqual(expect.arrayContaining([JSON.stringify(['profile']), JSON.stringify(['me'])]));
  });

  it('asks for the profile and the tax notice only once ready, and never inside the Later week', async () => {
    const early = stubFetch(ROUTES);
    const a = wrapBook(<ForYou data={HOME} ready={false} />);
    await waitFor(() => expect(callsTo(early, 'GET', '/api/review')).toHaveLength(1));
    expect(callsTo(early, 'GET', '/api/profile')).toEqual([]);
    expect(callsTo(early, 'GET', '/api/taxes/notice')).toEqual([]);
    a.unmount();
    vi.unstubAllGlobals();
    const inLater = stubFetch(ROUTES);
    wrapBook(<ForYou data={HOME} ready />, { profile: { seen: true, confirmed: false, later_until: LATER } });
    await waitFor(() => expect(callsTo(inLater, 'GET', '/api/taxes/notice')).toHaveLength(1));
    expect(callsTo(inLater, 'GET', '/api/profile')).toEqual([]);
  });

  it('a viewer reads the rows with no actions, and no Review row', async () => {
    stubFetch({ ...ROUTES, '/api/review': REVIEW(12) });
    wrapBook(<ForYou data={ONE_EVENT} ready />, { role: 'viewer' });
    expect(await screen.findByText(SYNC)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('button', { name: /^Dismiss/ })).toBeNull());
    expect(within(rows()[0]).queryByRole('link')).toBeNull();
    expect(screen.queryByText(/to sort in Review/)).toBeNull();
  });

  it('"Nothing needs you." keeps the card, with the background line at its foot for everyone', async () => {
    stubFetch({ ...ROUTES, '/api/review': REVIEW(0, { pending: 230, done: 420, waiting: false }) });
    wrapBook(<ForYou data={HOME} ready />, { role: 'viewer' });
    expect(screen.getByText('Nothing needs you.')).toBeInTheDocument();
    expect(await screen.findByTestId('background-line')).toHaveTextContent('Categorizing in the background: 420 of 650');
  });
});
