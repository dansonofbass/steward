import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Txn } from '../../../api/types';
import { callsTo, ME, reply, stubFetch, wrapBook } from '../../../test-utils';
import Review from '../../Review';

beforeEach(() => { localStorage.clear(); localStorage.setItem('steward-celebrations', 'off'); });
afterEach(() => { vi.restoreAllMocks(); });

const T = (id: number, extra: Partial<Txn> = {}): Txn => ({
  id, account_id: 1, account_name: 'Rewards Card', posted_at: '2026-10-16', amount_cents: -8072, raw_description: `SHOP ${id}`,
  merchant: null, category: 'uncategorized', is_business: false, is_transfer: false, business_pct: 0, business_line: null,
  business_source: 'none', category_source: 'none', reviewed_at: null, from_bank: true, note_count: 0, reason: 'unknown',
  guess: null, matching: 0, reimburse_ok: false, ...extra,
});
const GREEN = T(1, { raw_description: 'GREENLEAF MARKET', reason: 'unsure', guess: 'groceries', matching: 6 });
const NOODLE = T(2, { raw_description: 'NOODLE HOUSE', amount_cents: -4805, posted_at: '2026-10-15', reason: 'unsure', guess: 'dining' });
const ZELLE = T(3, { raw_description: 'ZELLE TO SAM', merchant: 'Zelle', reason: 'p2p' });
const ROWS = [GREEN, NOODLE, ZELLE, T(4)];
const TOP = ['groceries', 'dining', 'shopping', 'personal', 'transport', 'subscriptions'];
const Q = (rows: Txn[], more: object = {}) => ({ uncategorized: rows, count: rows.length, duplicates: [], duplicate_count: 0,
  top_categories: TOP, business: [], business_count: 0, ...more });
const SORTED = (t: Txn, category: string, ids: number[] = []) =>
  ({ ...t, category, result: { category, applied: ids.length, ids, rule: 'made', undo: `tok-${t.id}` } });
const cards = () => screen.getAllByTestId('focus-card');
const current = () => cards().find((c) => c.dataset.role === 'current')!;
const bar = () => screen.findByTestId('focus-bar');
const right = (b: HTMLElement) => within(b).getAllByRole('button')[1];
const toast = () => document.querySelector('.undo-toast');
const top = () => screen.getByTestId('review-top');

describe('Focus (review focus, decision 1): one card at a time, by default', () => {
  it('shows the card, the next one behind it inert, and the two buttons', async () => {
    stubFetch({ '/api/review': Q(ROWS) });
    wrapBook(<Review />);
    const b = await bar();
    expect(within(screen.getByRole('group', { name: 'View' })).getByRole('button', { name: 'Focus' })).toHaveAttribute('aria-pressed', 'true');
    const c = current();
    expect(c).toHaveAccessibleName('GREENLEAF MARKET');
    expect(within(c).getByText('Oct 16 · Rewards Card')).toBeInTheDocument();
    expect(c.querySelector('.fcard__probably')).toHaveTextContent('Probably Groceries');
    expect(within(c).getByText("Steward wasn't sure enough to sort it.")).toBeInTheDocument();
    expect(within(within(c).getByRole('group', { name: 'Category' })).getAllByRole('button').map((x) => x.textContent))
      .toEqual(['Groceries', 'Eating out', 'Shopping', 'Personal', 'More…']);
    expect(within(c).getByRole('checkbox', { name: 'Also the 6 like it' })).toBeChecked();
    expect(within(b).getByRole('button', { name: 'Snooze' })).toHaveTextContent('‹ Snooze');
    expect(right(b)).toHaveAccessibleName('Groceries');
    expect(right(b)).toHaveTextContent('Groceries ›');
    const next = cards().find((x) => x.dataset.role === 'next')!;
    expect(next.dataset.id).toBe('2');
    expect(next).toHaveAttribute('aria-hidden', 'true');
    expect(next).toHaveAttribute('inert');
    expect(cards()).toHaveLength(2);
    expect(top()).toHaveTextContent('4 left');
    expect(top().querySelector('.rtop__track')).toHaveAttribute('aria-hidden', 'true');
  });

  it('without a guess the right button reads All categories and opens them (P4)', async () => {
    stubFetch({ '/api/review': Q([ZELLE, T(4)]) });
    wrapBook(<Review />);
    const b = await bar();
    expect(current()).toHaveTextContent("A Zelle payment: the description doesn't say what it was for.");
    expect(current().querySelector('.fcard__probably')).toBeNull();
    expect(right(b)).toHaveTextContent('All categories ›');
    fireEvent.click(right(b));
    expect(screen.getByRole('dialog', { name: 'Category' })).toBeInTheDocument();
  });

  it('the card moves on only after the server confirms the sort (P8), skipping the rows it spread to', async () => {
    let answer!: (r: Response) => void;
    const fetchMock = stubFetch({ '/api/review': Q(ROWS), 'PATCH /api/transactions/1': () => new Promise<Response>((res) => { answer = res; }) });
    wrapBook(<Review />);
    fireEvent.click(right(await bar()));
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/transactions/1')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/1')[0].body).toEqual({ category: 'groceries', apply_to_matching: true });
    expect(current().dataset.id).toBe('1');                              // nothing moves before the server says so
    expect(cards().some((c) => c.dataset.role === 'leaving')).toBe(false);
    expect(toast()).toBeNull();
    act(() => { answer(reply(SORTED(GREEN, 'groceries', [2, 11, 12, 13, 14, 15]))); });
    await waitFor(() => expect(current().dataset.id).toBe('3'));         // Noodle House (2) was sorted with it
    expect(toast()).toHaveTextContent('SORTED · GREENLEAF MARKET + 6 like it → Groceries · Undo');
    expect(top()).toHaveTextContent('2 left');
  });

  it('a double tap sends one sort (Review Focus 3)', async () => {
    let answer!: (r: Response) => void;
    const fetchMock = stubFetch({ '/api/review': Q(ROWS), 'PATCH /api/transactions/1': () => new Promise<Response>((res) => { answer = res; }) });
    wrapBook(<Review />);
    const b = await bar();
    fireEvent.click(right(b));
    fireEvent.click(right(b));
    act(() => { answer(reply(SORTED(GREEN, 'groceries'))); });
    await waitFor(() => expect(current().dataset.id).toBe('2'));
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/')).toHaveLength(1);
  });

  it('Snooze slides it on with "Snoozed · back Nov 6"; a failure keeps the card and says nothing changed', async () => {
    stubFetch({ '/api/review': Q(ROWS), 'POST /api/review/1/snooze': { undo: 'tok-s', until: '2026-11-06' },
      'PATCH /api/transactions/2': () => reply({ error: 'Nope.' }, 500) });
    wrapBook(<Review />);
    fireEvent.click(within(await bar()).getByRole('button', { name: 'Snooze' }));
    await waitFor(() => expect(current().dataset.id).toBe('2'));
    expect(toast()).toHaveTextContent('Snoozed · back Nov 6 · Undo');
    fireEvent.click(right(await bar()));
    await waitFor(() => expect(current()).toHaveTextContent('Not saved. Nope. Nothing changed.'));
    expect(current().dataset.id).toBe('2');
    expect(toast()).toHaveTextContent('Snoozed · back Nov 6');           // the failed sort made no toast
  });

  it('three actions, then Z three times: each Undo in reverse order brings its card back as it was', async () => {
    const fetchMock = stubFetch({ '/api/review': Q(ROWS),
      'PATCH /api/transactions/1': SORTED(GREEN, 'groceries'), 'POST /api/review/2/snooze': { undo: 'tok-2', until: '2026-11-06' },
      'PATCH /api/transactions/3': SORTED(ZELLE, 'shopping'),
      'POST /api/undo/tok-3': { undone: 1, transaction: ZELLE }, 'POST /api/undo/tok-2': { undone: 1, transaction: NOODLE },
      'POST /api/undo/tok-1': { undone: 1, transaction: { ...GREEN, matching: undefined, reason: undefined, guess: undefined } } });
    wrapBook(<Review />);
    fireEvent.click(right(await bar()));
    await waitFor(() => expect(current().dataset.id).toBe('2'));
    fireEvent.click(within(await bar()).getByRole('button', { name: 'Snooze' }));
    await waitFor(() => expect(current().dataset.id).toBe('3'));
    fireEvent.click(within(current()).getByRole('button', { name: 'Shopping' }));
    await waitFor(() => expect(current().dataset.id).toBe('4'));
    for (const id of ['3', '2', '1']) {
      fireEvent.keyDown(document.body, { key: 'z' });
      await waitFor(() => expect(current().dataset.id).toBe(id));
      expect(within(current()).getByText('Undone.')).toBeInTheDocument();
    }
    expect(callsTo(fetchMock, 'POST', '/api/undo/').map((c) => c.url)).toEqual(['/api/undo/tok-3', '/api/undo/tok-2', '/api/undo/tok-1']);
    expect(within(current()).getByRole('checkbox', { name: 'Also the 6 like it' })).toBeChecked();
    expect(current().querySelector('.fcard__probably')).toHaveTextContent('Probably Groceries');
    expect(within(top()).getByRole('button', { name: 'Undo' })).toBeDisabled();
  });

  it('an Undo pressed before the reply waits for it, then sends once; a 409 drops it and says why', async () => {
    let answer!: (r: Response) => void;
    const fetchMock = stubFetch({ '/api/review': Q(ROWS),
      'PATCH /api/transactions/1': () => new Promise<Response>((res) => { answer = res; }),
      'POST /api/undo/tok-1': () => reply({ error: "That changed since, so it can't be undone." }, 409) });
    wrapBook(<Review />);
    fireEvent.click(right(await bar()));
    fireEvent.click(within(top()).getByRole('button', { name: 'Undo' }));
    expect(callsTo(fetchMock, 'POST', '/api/undo/')).toHaveLength(0);
    act(() => { answer(reply(SORTED(GREEN, 'groceries'))); });
    await waitFor(() => expect(toast()).toHaveTextContent("That changed since, so it can't be undone."));
    expect(callsTo(fetchMock, 'POST', '/api/undo/tok-1')).toHaveLength(1);
    expect(within(top()).getByRole('button', { name: 'Undo' })).toBeDisabled();
  });

  it('an undone card is current and live before the refetch lists it (Review Focus 1)', async () => {
    let undone = false;
    let sortedOnce = false;
    stubFetch({
      // After the sort the server no longer lists card 1; after the Undo, the refetch never answers in this test.
      '/api/review': () => (undone ? new Promise<Response>(() => {}) : reply(Q(ROWS.filter((r) => r.id !== 1 || !sortedOnce)))),
      'PATCH /api/transactions/1': () => { sortedOnce = true; return reply(SORTED(GREEN, 'groceries')); },
      'POST /api/undo/tok-1': () => { undone = true; return reply({ undone: 1, transaction: GREEN }); },
    });
    wrapBook(<Review />);
    fireEvent.click(right(await bar()));
    await waitFor(() => expect(current().dataset.id).toBe('2'));
    fireEvent.keyDown(document.body, { key: 'z' });
    await waitFor(() => expect(current().dataset.id).toBe('1'));
    expect(within(current()).queryByText('Already sorted.')).toBeNull();
    expect(right(await bar())).toHaveTextContent('Groceries ›');
    expect(document.activeElement).toBe(current());                     // focus goes to the returned card (P30)
  });

  it('a refetch never swaps the current card; sorted elsewhere it says so and offers Next (Review Focus 2, P32)', async () => {
    let rows = ROWS;
    stubFetch({ '/api/review': () => reply(Q(rows)) });
    const { qc } = wrapBook(<Review />);
    await bar();
    rows = [NOODLE, ZELLE, T(4), T(5)];                                  // card 1 was sorted on another device
    await act(async () => { await qc.invalidateQueries({ queryKey: ['review'] }); });
    expect(await within(current()).findByText('Already sorted.')).toBeInTheDocument();   // the observer tells React on the next tick
    expect(current().dataset.id).toBe('1');
    const b = await bar();
    expect(right(b)).toHaveTextContent('Next ›');
    expect(within(b).getByRole('button', { name: 'Snooze' })).toBeDisabled();
    fireEvent.click(right(b));
    expect(current().dataset.id).toBe('2');
  });

  it('the stack survives a switch to List, and Z there undoes the focus sort; the card returns at the end (Review Focus 4)', async () => {
    const fetchMock = stubFetch({ '/api/review': Q(ROWS), 'PATCH /api/transactions/1': SORTED(GREEN, 'groceries'),
      'POST /api/undo/tok-1': { undone: 1, transaction: GREEN } });
    wrapBook(<Review />);
    fireEvent.click(right(await bar()));
    await waitFor(() => expect(current().dataset.id).toBe('2'));
    fireEvent.click(within(screen.getByRole('group', { name: 'View' })).getByRole('button', { name: 'List' }));
    await waitFor(() => expect(screen.getAllByTestId('review-card').map((c) => c.dataset.id)).toEqual(['2', '3', '4']));
    expect(within(top()).getByRole('button', { name: 'Undo' })).toBeEnabled();
    fireEvent.keyDown(document.body, { key: 'z' });
    await waitFor(() => expect(screen.getAllByTestId('review-card').map((c) => c.dataset.id)).toEqual(['2', '3', '4', '1']));
    expect(callsTo(fetchMock, 'POST', '/api/undo/tok-1')).toHaveLength(1);
  });

  it("the toast's Undo brings its card back; the next action's toast replaces it", async () => {
    const fetchMock = stubFetch({ '/api/review': Q(ROWS), 'POST /api/review/1/snooze': { undo: 'tok-1', until: '2026-11-06' },
      'POST /api/review/2/snooze': { undo: 'tok-2', until: '2026-11-06' }, 'POST /api/undo/tok-2': { undone: 1, transaction: NOODLE } });
    wrapBook(<Review />);
    fireEvent.click(within(await bar()).getByRole('button', { name: 'Snooze' }));
    await waitFor(() => expect(current().dataset.id).toBe('2'));
    fireEvent.click(within(await bar()).getByRole('button', { name: 'Snooze' }));
    await waitFor(() => expect(current().dataset.id).toBe('3'));
    expect(document.querySelectorAll('.undo-toast')).toHaveLength(1);    // one toast at a time (P16)
    fireEvent.click(within(toast() as HTMLElement).getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(current().dataset.id).toBe('2'));
    expect(callsTo(fetchMock, 'POST', '/api/undo/').map((c) => c.url)).toEqual(['/api/undo/tok-2']);
    expect(toast()).toBeNull();
  });

  it('switching views clears the list’s slim rows; the stack stays', async () => {
    stubFetch({ '/api/review': Q(ROWS), 'PATCH /api/transactions/2': SORTED(NOODLE, 'dining') });
    wrapBook(<Review />);
    await bar();
    const group = () => within(screen.getByRole('group', { name: 'View' }));
    fireEvent.click(group().getByRole('button', { name: 'List' }));
    const noodle = (await screen.findAllByTestId('review-card')).find((c) => c.dataset.id === '2')!;
    fireEvent.click(within(noodle).getByRole('button', { name: 'Eating out' }));
    await screen.findByTestId('slim-row');
    fireEvent.click(group().getByRole('button', { name: 'Focus' }));
    await bar();
    fireEvent.click(group().getByRole('button', { name: 'List' }));
    await waitFor(() => expect(screen.getAllByTestId('review-card').map((c) => c.dataset.id)).toEqual(['1', '3', '4']));
    expect(screen.queryByTestId('slim-row')).toBeNull();
    expect(within(top()).getByRole('button', { name: 'Undo' })).toBeEnabled();
  });

  it('pressing the view you are already in changes nothing', async () => {
    stubFetch({ '/api/review': Q(ROWS) });
    wrapBook(<Review />);
    await bar();
    const group = () => within(screen.getByRole('group', { name: 'View' }));
    fireEvent.click(group().getByRole('button', { name: 'List' }));
    await screen.findAllByTestId('review-card');
    fireEvent.click(group().getByRole('button', { name: 'List' }));
    expect(screen.getAllByTestId('review-card').map((c) => c.dataset.id)).toEqual(['1', '2', '3', '4']);
  });

  it('the acted card leaves with transform and opacity only, and under reduced motion it just swaps', async () => {
    const animate = vi.fn((_f: Keyframe[], _o?: KeyframeAnimationOptions) => ({ finished: Promise.resolve(), cancel: () => {} }));
    Object.defineProperty(HTMLElement.prototype, 'animate', { configurable: true, value: animate });
    try {
      stubFetch({ '/api/review': Q(ROWS), 'PATCH /api/transactions/1': SORTED(GREEN, 'groceries'), 'PATCH /api/transactions/2': SORTED(NOODLE, 'dining') });
      const first = wrapBook(<Review />);
      fireEvent.click(right(await bar()));
      await waitFor(() => expect(current().dataset.id).toBe('2'));
      const [frames, opts] = animate.mock.calls[0];
      expect(new Set(frames.flatMap((f) => Object.keys(f)))).toEqual(new Set(['transform', 'opacity']));
      expect(opts).toMatchObject({ duration: 220 });
      await waitFor(() => expect(cards().some((c) => c.dataset.role === 'leaving')).toBe(false));
      first.unmount();
      animate.mockClear();
      vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener: () => {}, removeEventListener: () => {} }));
      wrapBook(<Review />);
      fireEvent.click(right(await bar()));
      await waitFor(() => expect(current().dataset.id).toBe('2'));
      expect(cards().some((c) => c.dataset.role === 'leaving')).toBe(false);
      expect(animate).not.toHaveBeenCalled();
    } finally {
      delete (HTMLElement.prototype as { animate?: unknown }).animate;
    }
  });

  it('the toggle saves the view per person; a viewer sees the list only (P1, P3)', async () => {
    stubFetch({ '/api/review': Q(ROWS), '/api/auth/me': ME });
    const first = wrapBook(<Review />);
    await bar();
    fireEvent.click(within(screen.getByRole('group', { name: 'View' })).getByRole('button', { name: 'List' }));
    expect(localStorage.getItem('steward-review-view:1')).toBe('list');
    first.unmount();
    const second = wrapBook(<Review />);
    expect(await screen.findAllByTestId('review-card')).toHaveLength(4);
    expect(screen.queryByTestId('focus-card')).toBeNull();
    second.unmount();
    localStorage.clear();
    wrapBook(<Review />, { role: 'viewer' });
    expect(await screen.findAllByTestId('review-card')).toHaveLength(4);
    expect(screen.queryByRole('group', { name: 'View' })).toBeNull();
    expect(screen.queryByTestId('focus-card')).toBeNull();
  });

  it('the header keeps business, duplicates and sorted by Steward; Select is the list’s only (P25)', async () => {
    stubFetch({ '/api/review': Q(ROWS, { business: [], business_count: 3, duplicate_count: 2, sorted_count: 12 }) });
    wrapBook(<Review />);
    await bar();
    expect([...screen.getByTestId('review-counts').children].map((s) => s.textContent))
      .toEqual(['3 business or personal', '2 possible duplicates', '12 sorted by Steward, not checked yet']);
    expect(top()).toHaveTextContent('4 left');
    expect(screen.queryByRole('button', { name: 'Select' })).toBeNull();
  });
});
