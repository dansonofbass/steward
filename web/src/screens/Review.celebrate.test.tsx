import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { withCelebrate } from '../lib/celebrations';
import { useFakeTimers } from '../test-clock';
import { inList, reply, stubFetch, wrapBook } from '../test-utils';
import Review from './Review';

const fx = vi.hoisted(() => ({
  sorted: vi.fn((_c: { card: HTMLElement; category: string; applied: number; sound: boolean; mark?: boolean }) => () => {}),
  quiet: vi.fn((_c: { card: HTMLElement; kind: string }) => () => {}),
  pop: vi.fn((_text: string) => {}),
  sunrise: vi.fn((_el: HTMLElement) => {}),
  acorn: vi.fn((_o: { svg: SVGSVGElement; motion: string; sound?: boolean }) => () => {}),
}));
vi.mock('../celebrate/celebrate', () => fx);

const TXN = { id: 1, account_id: 1, account_name: 'Checking', posted_at: '2026-10-10', amount_cents: -1200, raw_description: 'A SHOP', merchant: null,
  category: 'uncategorized', is_business: false, is_transfer: false, business_pct: 0, business_line: null, business_source: 'none',
  category_source: 'none', reviewed_at: null, from_bank: true, note_count: 0, matching: 0 };
const row = (id: number, raw = `SHOP ${id}`, matching = 0) => ({ ...TXN, id, raw_description: raw, matching });
const queue = (rows: object[]) => ({ uncategorized: rows, count: rows.length, duplicates: [], duplicate_count: 0, top_categories: ['transport'], business: [], business_count: 0 });
const sortedAs = (r: { id: number }, ids: number[] = []) => ({ ...r, category: 'transport', result: { category: 'transport', applied: ids.length, ids, rule: 'made', undo: `t${r.id}` } });
const routes = (rows: { id: number }[]) => Object.fromEntries(rows.map((r) => [`PATCH /api/transactions/${r.id}`, sortedAs(r)]));
const byId = (testId: string, id: number) => () => {
  const el = screen.queryAllByTestId(testId).find((x) => x.dataset.id === String(id));
  if (!el) throw new Error(`no ${testId} ${id} yet`);
  return el;
};
// Waits for that very card, then its chip by text: getByRole's accessible-name pass over the card cost more than the
// rest of a sort, and these tests sort up to thirteen times (on a loaded machine they ran past the test's ceiling).
const sortCard = async (id: number) => {
  const c = await waitFor(byId('review-card', id));
  fireEvent.click(within(c).getByText('Getting around', { selector: 'button' }));
  return waitFor(byId('slim-row', id));
};

// The celebrate chunk loads before the first test, so no test waits on a dynamic import, and a celebration a test
// started never lands in the next one. Each test runs on the fake clock, so a wait's ceiling is fake time, not load.
beforeAll(async () => { expect(await withCelebrate(() => true)).toBe(true); });
beforeEach(() => {
  useFakeTimers();
  localStorage.clear();
  for (const f of Object.values(fx)) f.mockClear();
  vi.spyOn(Math, 'random').mockReturnValue(0.5);   // no golden, a cheer gap of 4
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('Review celebrates (sorting redesign, Celebrations; review focus P18, P19)', () => {
  it("a sort plays its category's moment from the slim row, with no second stamp, and the ding with Sound", async () => {
    localStorage.setItem('steward-sound', 'on');
    const nine = row(9, 'UNION SERVICE CENTER', 6);
    stubFetch({ ...inList(), '/api/review': queue([nine]), 'PATCH /api/transactions/9': sortedAs(nine, [20, 21, 22, 23, 24, 25]) });
    wrapBook(<Review />);
    const slim = await sortCard(9);
    await waitFor(() => expect(fx.sorted).toHaveBeenCalledWith(expect.objectContaining({ card: slim, category: 'transport', applied: 6, sound: true, mark: false })));
  });

  it('Ten in a row at the tenth sort, once; an Undo breaks the run', async () => {
    const rows = Array.from({ length: 12 }, (_, i) => row(i + 1));
    stubFetch({ ...inList(), '/api/review': queue(rows), ...routes(rows), 'POST /api/undo/t9': { undone: 1, transaction: rows[8] } });
    wrapBook(<Review />);
    for (const id of [1, 2, 3, 4, 5, 6, 7, 8, 9]) await sortCard(id);
    fireEvent.keyDown(document.body, { key: 'z' });                       // the run breaks at nine
    await waitFor(() => expect(screen.getAllByTestId('review-card').some((c) => c.dataset.id === '9')).toBe(true));
    for (const id of [10, 11, 12, 9]) await sortCard(id);                 // thirteen sorts, but four since the Undo
    expect(fx.pop).not.toHaveBeenCalled();
  });

  it('Ten in a row pops once at the tenth sort in a row', async () => {
    const rows = Array.from({ length: 11 }, (_, i) => row(i + 1));
    stubFetch({ ...inList(), '/api/review': queue(rows), ...routes(rows) });
    wrapBook(<Review />);
    for (let id = 1; id <= 11; id++) await sortCard(id);
    await waitFor(() => expect(fx.pop).toHaveBeenCalledWith('Ten in a row'));
    expect(fx.pop).toHaveBeenCalledOnce();
  });

  it('cheers the 100th sort on this device once', async () => {
    localStorage.setItem('steward-sorts', JSON.stringify({ total: 99, day: '2000-01-01', today: 0 }));
    const rows = [row(1), row(2)];
    stubFetch({ ...inList(), '/api/review': queue(rows), ...routes(rows) });
    wrapBook(<Review />);
    await sortCard(1);
    await waitFor(() => expect(fx.pop).toHaveBeenCalledWith("That's 100 sorted on this device!"));
    await sortCard(2);
    await waitFor(() => expect(fx.sorted).toHaveBeenCalledTimes(2));
    expect(fx.pop).toHaveBeenCalledOnce();
  });

  it('the last card going brings All caught up!, how many were sorted today, and the sunrise once', async () => {
    let calls = 0;
    const nine = row(9, 'UNION SERVICE CENTER', 2);
    stubFetch({ ...inList(), '/api/review': () => reply(++calls === 1 ? queue([nine]) : queue([])), 'PATCH /api/transactions/9': sortedAs(nine, [30, 31]) });
    wrapBook(<Review />);
    await sortCard(9);
    expect(await screen.findByText('All caught up!')).toBeInTheDocument();
    expect(screen.getByText('You sorted 3 today.')).toBeInTheDocument();
    await waitFor(() => expect(fx.sunrise).toHaveBeenCalledOnce());
  });

  it('Snooze plays no sort moment and breaks no milestone', async () => {
    const nine = row(9, 'UNION SERVICE CENTER');
    stubFetch({ ...inList(), '/api/review': queue([nine]), 'POST /api/review/9/snooze': { undo: 's', until: '2026-11-04' } });
    wrapBook(<Review />);
    fireEvent.click(within(await screen.findByTestId('review-card')).getByRole('button', { name: 'Snooze' }));
    await screen.findByTestId('slim-row');
    expect(fx.sorted).not.toHaveBeenCalled();
    expect(fx.pop).not.toHaveBeenCalled();
  });
});
