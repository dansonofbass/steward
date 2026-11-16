import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Txn } from '../../../api/types';
import { callsTo, reply, stubFetch, wrapBook } from '../../../test-utils';
import Review from '../../Review';

const fx = vi.hoisted(() => ({
  sorted: vi.fn((_c: { tick?: boolean }) => () => {}),
  quiet: vi.fn(() => () => {}),
  pop: vi.fn(),
  sunrise: vi.fn(),
  acorn: vi.fn(() => () => {}),
  winMoment: vi.fn(() => () => {}),
}));
vi.mock('../../../celebrate/celebrate', () => fx);

const vibrate = vi.fn();
beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('steward-celebrations', 'off');
  Object.defineProperty(navigator, 'vibrate', { configurable: true, value: vibrate });
  vibrate.mockClear();
  for (const f of Object.values(fx)) f.mockClear();
});
afterEach(() => { vi.restoreAllMocks(); });

const T = (id: number, extra: Partial<Txn> = {}): Txn => ({
  id, account_id: 1, account_name: 'Rewards Card', posted_at: '2026-10-16', amount_cents: -8072, raw_description: `SHOP ${id}`,
  merchant: null, category: 'uncategorized', is_business: false, is_transfer: false, business_pct: 0, business_line: null,
  business_source: 'none', category_source: 'none', reviewed_at: null, from_bank: true, note_count: 0, reason: 'unsure',
  guess: 'groceries', matching: 0, reimburse_ok: false, ...extra,
});
const ROWS = [T(1, { raw_description: 'GREENLEAF MARKET' }), T(2), T(3)];
const Q = (rows: Txn[]) => ({ uncategorized: rows, count: rows.length, duplicates: [], duplicate_count: 0,
  top_categories: ['groceries', 'dining', 'shopping', 'personal'], business: [], business_count: 0 });
const SORTED = (t: Txn, category = 'groceries') => ({ ...t, category, result: { category, applied: 0, ids: [], rule: 'made', undo: `tok-${t.id}` } });
const current = () => screen.getAllByTestId('focus-card').find((c) => c.dataset.role === 'current')!;
/** Synthetic pointer events: jsdom's PointerEvent support varies, so a MouseEvent carries pointerType and pointerId. */
const ptr = (el: Element, type: string, x: number, y: number, o: { pointerType?: string; pointerId?: number; isPrimary?: boolean } = {}) => {
  const e = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y });
  Object.defineProperties(e, { pointerType: { value: o.pointerType ?? 'touch' }, pointerId: { value: o.pointerId ?? 1 }, isPrimary: { value: o.isPrimary ?? true } });
  fireEvent(el, e);
};
const sized = (el: HTMLElement) => vi.spyOn(el, 'getBoundingClientRect').mockReturnValue(
  { top: 0, left: 0, right: 360, bottom: 400, width: 360, height: 400, x: 0, y: 0, toJSON() {} } as DOMRect);
/** A drag from (100, 300) by (dx, dy), in two moves, then a release. The card is 360 × 400: 108 px sideways, 100 up. */
const drag = (el: HTMLElement, dx: number, dy: number, o: Parameters<typeof ptr>[4] = {}, at: Element = el) => {
  sized(el);
  ptr(at, 'pointerdown', 100, 300, o);
  ptr(at, 'pointermove', 100 + dx / 2, 300 + dy / 2, o);
  ptr(at, 'pointermove', 100 + dx, 300 + dy, o);
  ptr(at, 'pointerup', 100 + dx, 300 + dy, o);
};

describe('swipes in focus (review focus, Gestures; touch and pen only, P11)', () => {
  it('right past the threshold takes the guess with one haptic tick; the next card is current when the reply lands', async () => {
    const fetchMock = stubFetch({ '/api/review': Q(ROWS), 'PATCH /api/transactions/1': SORTED(ROWS[0]) });
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    drag(current(), 150, 0);
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/transactions/1')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/1')[0].body).toEqual({ category: 'groceries' });
    expect(vibrate).toHaveBeenCalledTimes(1);
    expect(vibrate).toHaveBeenCalledWith(10);
    await waitFor(() => expect(current().dataset.id).toBe('2'));
    expect(document.querySelector('.undo-toast')).toHaveTextContent('SORTED · GREENLEAF MARKET → Groceries');
  });

  it('left snoozes for a week; up opens all categories and the card springs back', async () => {
    stubFetch({ '/api/review': Q(ROWS), 'POST /api/review/1/snooze': { undo: 'tok-1', until: '2026-11-06' } });
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    drag(current(), -150, 0);
    await waitFor(() => expect(current().dataset.id).toBe('2'));
    expect(document.querySelector('.undo-toast')).toHaveTextContent('Snoozed · back Nov 6 · Undo');
    drag(current(), 0, -150);
    expect(screen.getByRole('dialog', { name: 'Category' })).toBeInTheDocument();
    expect(current().style.transform).toBe('');
    expect(current().dataset.flown).toBeUndefined();
  });

  it('short of the threshold nothing happens and the card is back at rest', async () => {
    const fetchMock = stubFetch({ '/api/review': Q(ROWS) });
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    drag(current(), 80, 0);
    drag(current(), 0, -60);
    drag(current(), 0, 200);                        // down does nothing
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/')).toHaveLength(0);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(current().style.transform).toBe('');
    expect(vibrate).not.toHaveBeenCalled();
  });

  it('a mouse drag does nothing, and a second finger is ignored', async () => {
    const fetchMock = stubFetch({ '/api/review': Q(ROWS) });
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    drag(current(), 150, 0, { pointerType: 'mouse' });
    drag(current(), 150, 0, { isPrimary: false, pointerId: 2 });
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/')).toHaveLength(0);
  });

  it('a drag that starts on a chip never clicks it; a tap afterwards does (Review Focus 5, P12)', async () => {
    const fetchMock = stubFetch({ '/api/review': Q(ROWS), 'PATCH /api/transactions/1': SORTED(ROWS[0], 'shopping') });
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    const chip = within(current()).getByRole('button', { name: 'Shopping' });
    drag(current(), 40, 0, {}, chip);
    fireEvent.click(chip);                           // the click that ends a drag is swallowed
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/')).toHaveLength(0);
    ptr(chip, 'pointerdown', 100, 300);
    ptr(chip, 'pointerup', 100, 300);
    fireEvent.click(chip);
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/transactions/1')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/1')[0].body).toEqual({ category: 'shopping' });
  });

  it('a failed swipe brings the card back with Not saved', async () => {
    stubFetch({ '/api/review': Q(ROWS), 'PATCH /api/transactions/1': () => reply({ error: 'Nope.' }, 500) });
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    drag(current(), 150, 0);
    await waitFor(() => expect(current()).toHaveTextContent('Not saved. Nope. Nothing changed.'));
    expect(current().dataset.id).toBe('1');
    expect(current().dataset.flown).toBeUndefined();
  });

  it('without a guess a right swipe opens all categories and springs back (P4)', async () => {
    const fetchMock = stubFetch({ '/api/review': Q([T(5, { guess: null, reason: 'unknown' }), T(6)]) });
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    drag(current(), 150, 0);
    expect(screen.getByRole('dialog', { name: 'Category' })).toBeInTheDocument();
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/')).toHaveLength(0);
    expect(current().dataset.flown).toBeUndefined();
  });

  it('with Swipe to sort off no gesture is attached, and the buttons still sort', async () => {
    localStorage.setItem('steward-swipe', 'off');
    const fetchMock = stubFetch({ '/api/review': Q(ROWS), 'PATCH /api/transactions/1': SORTED(ROWS[0]) });
    wrapBook(<Review />);
    const bar = await screen.findByTestId('focus-bar');
    drag(current(), 150, 0);
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/')).toHaveLength(0);
    expect(current().querySelector('.fcard__edge')).toBeNull();
    fireEvent.click(within(bar).getAllByRole('button')[1]);
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/transactions/1')).toHaveLength(1));
  });

  it('one haptic per action: after a swipe ticked, the stamp skips its landing tick (P33)', async () => {
    localStorage.removeItem('steward-celebrations');
    stubFetch({ '/api/review': Q(ROWS), 'PATCH /api/transactions/1': SORTED(ROWS[0]), 'PATCH /api/transactions/2': SORTED(ROWS[1]) });
    wrapBook(<Review />);
    const bar = await screen.findByTestId('focus-bar');
    drag(current(), 150, 0);
    await waitFor(() => expect(fx.sorted).toHaveBeenCalledWith(expect.objectContaining({ tick: false })));
    await waitFor(() => expect(current().dataset.id).toBe('2'));
    await act(async () => { fireEvent.click(within(bar).getAllByRole('button')[1]); });
    await waitFor(() => expect(fx.sorted).toHaveBeenCalledTimes(2));
    expect(fx.sorted.mock.calls[1][0]).toMatchObject({ tick: true });
  });
});
