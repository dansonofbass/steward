import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Txn } from '../api/types';
import { callsTo, inList, reply, stubFetch, wrapBook } from '../test-utils';
import Review from './Review';

beforeEach(() => { localStorage.clear(); localStorage.setItem('steward-celebrations', 'off'); vi.spyOn(Math, 'random').mockReturnValue(0.5); });   // no golden, a cheer gap of 4
afterEach(() => { vi.restoreAllMocks(); });

const T = (id: number, extra: Partial<Txn> = {}): Txn => ({
  id, account_id: 1, account_name: 'Checking', posted_at: '2026-10-10', amount_cents: -1200, raw_description: `SHOP ${id}`,
  merchant: null, category: 'uncategorized', is_business: false, is_transfer: false, business_pct: 0, business_line: null,
  business_source: 'none', category_source: 'none', reviewed_at: null, from_bank: true, note_count: 0, reason: 'unknown',
  guess: null, matching: 0, reimburse_ok: false, ...extra,
});
const GREEN = T(1, { raw_description: 'GREENLEAF MARKET', reason: 'unsure', guess: 'groceries', matching: 6 });
const ROWS = [GREEN, T(2), T(3), T(4, { raw_description: 'GREENLEAF MARKET 4' })];
const Q = (rows: Txn[], more: object = {}) => ({ uncategorized: rows, count: rows.length, duplicates: [], duplicate_count: 0,
  top_categories: ['groceries', 'dining'], business: [], business_count: 0, ...more });
const SORTED = (t: Txn, category: string, ids: number[] = [], reimburse: object | null = null) =>
  ({ ...t, category, result: { category, applied: ids.length, ids, rule: 'made', undo: `tok-${t.id}`, reimburse } });
const card = (id: number) => screen.getAllByTestId('review-card').find((c) => c.dataset.id === String(id))!;
const slim = (id: number) => {
  const s = screen.getAllByTestId('slim-row').find((c) => c.dataset.id === String(id));
  if (!s) throw new Error(`no slim row ${id} yet`);
  return s;
};
const ready = async (id: number) => { await screen.findAllByTestId('review-card'); return card(id); };
const slots = () => [...document.querySelectorAll<HTMLElement>('.rcards > [data-id]')]
  .map((el) => `${el.dataset.id}:${el.dataset.testid === 'slim-row' ? 'slim' : 'card'}`);
const toast = () => document.querySelector('.undo-toast');
const top = () => screen.getByTestId('review-top');

describe('the list (review focus P20, P21): a card acted on becomes a slim row in its place', () => {
  it('a sort leaves a slim row where the card was, marks its matches, keeps the order, and the toast names it with Undo', async () => {
    const fetchMock = stubFetch({ ...inList(), '/api/review': Q(ROWS), 'PATCH /api/transactions/1': SORTED(GREEN, 'groceries', [4]) });
    wrapBook(<Review />);
    expect(within(await screen.findByTestId('review-top')).getByRole('button', { name: 'Undo' })).toBeDisabled();
    expect(top()).toHaveTextContent('4 left');
    expect(within(card(1)).getByRole('checkbox', { name: 'Also the 6 like it' })).toBeChecked();
    expect(within(card(1)).getByText("Steward wasn't sure enough to sort it.")).toBeInTheDocument();
    fireEvent.click(within(card(1)).getByRole('button', { name: 'Groceries' }));
    await waitFor(() => expect(slots()).toEqual(['1:slim', '2:card', '3:card', '4:slim']));
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/1')[0].body).toEqual({ category: 'groceries', apply_to_matching: true });
    expect(slim(1)).toHaveTextContent('SORTED · GREENLEAF MARKET + 1 like it as Groceries · Undo');
    expect(slim(4)).toHaveTextContent('SORTED · GREENLEAF MARKET 4 as Groceries');
    expect(within(slim(4)).queryByRole('button', { name: 'Undo' })).toBeNull();      // the parent's Undo restores it
    expect(toast()).toHaveTextContent('SORTED · GREENLEAF MARKET + 1 like it → Groceries · Undo');
    expect(top()).toHaveTextContent('2 left');
    expect(within(top()).getByRole('button', { name: 'Undo' })).toBeEnabled();
  });

  it("the slim row's Undo grows the card back, as it was, with Undone., and its matches come back", async () => {
    const fetchMock = stubFetch({ ...inList(), '/api/review': Q(ROWS), 'PATCH /api/transactions/1': SORTED(GREEN, 'groceries', [4]),
      'POST /api/undo/tok-1': { undone: 2, transaction: { ...GREEN, reason: undefined, guess: undefined, matching: undefined } } });
    wrapBook(<Review />);
    fireEvent.click(within(await ready(1)).getByRole('button', { name: 'Groceries' }));
    fireEvent.click(within(await waitFor(() => slim(1))).getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(slots()).toEqual(['1:card', '2:card', '3:card', '4:card']));
    expect(callsTo(fetchMock, 'POST', '/api/undo/tok-1')).toHaveLength(1);
    expect(within(card(1)).getByText('Undone.')).toBeInTheDocument();
    expect(within(card(1)).getByRole('checkbox', { name: 'Also the 6 like it' })).toBeChecked();
    expect(toast()).toBeNull();
  });

  it('Snooze and Ignore leave slim rows, and their toasts are plain sentences', async () => {
    stubFetch({ ...inList(), '/api/review': Q(ROWS), 'POST /api/review/2/snooze': { undo: 'tok-2', until: '2026-11-06' }, 'POST /api/review/3/ignore': { undo: 'tok-3' } });
    wrapBook(<Review />);
    fireEvent.click(within(await ready(2)).getByRole('button', { name: 'Snooze' }));
    await waitFor(() => expect(slim(2)).toHaveTextContent('SNOOZED · SHOP 2 · back Nov 6 · Undo'));
    expect(toast()).toHaveTextContent('Snoozed · back Nov 6 · Undo');
    fireEvent.click(within(card(3)).getByRole('button', { name: 'Ignore' }));
    await waitFor(() => expect(slim(3)).toHaveTextContent('IGNORED · SHOP 3 · Undo'));
    expect(toast()).toHaveTextContent('Ignored · SHOP 3 · Undo');
    expect(slots()).toEqual(['1:card', '2:slim', '3:slim', '4:card']);
  });

  it("Z undoes the newest first; a 409 drops that entry with the server's words, and ↶ is disabled once empty", async () => {
    const fetchMock = stubFetch({ ...inList(), '/api/review': Q(ROWS), 'PATCH /api/transactions/1': SORTED(GREEN, 'groceries'),
      'POST /api/review/2/snooze': { undo: 'tok-2', until: '2026-11-06' },
      'POST /api/undo/tok-2': { undone: 1, transaction: T(2) },
      'POST /api/undo/tok-1': () => reply({ error: "That changed since, so it can't be undone." }, 409) });
    wrapBook(<Review />);
    fireEvent.click(within(await ready(1)).getByRole('button', { name: 'Groceries' }));
    await waitFor(() => slim(1));
    fireEvent.click(within(card(2)).getByRole('button', { name: 'Snooze' }));
    await waitFor(() => slim(2));
    fireEvent.keyDown(document.body, { key: 'z' });
    await waitFor(() => expect(slots()).toEqual(['1:slim', '2:card', '3:card', '4:card']));
    fireEvent.keyDown(document.body, { key: 'Z' });
    await waitFor(() => expect(toast()).toHaveTextContent("That changed since, so it can't be undone."));
    expect(within(toast() as HTMLElement).queryByRole('button', { name: 'Undo' })).toBeNull();
    expect(within(slim(1)).queryByRole('button', { name: 'Undo' })).toBeNull();     // its entry was dropped
    expect(callsTo(fetchMock, 'POST', '/api/undo/').map((c) => c.url)).toEqual(['/api/undo/tok-2', '/api/undo/tok-1']);
    expect(within(top()).getByRole('button', { name: 'Undo' })).toBeDisabled();
  });

  it('an Undo pressed while the sort is still saving waits for it, then sends once', async () => {
    let answer!: (r: Response) => void;
    const fetchMock = stubFetch({ ...inList(), '/api/review': Q(ROWS),
      'PATCH /api/transactions/1': () => new Promise<Response>((res) => { answer = res; }),
      'POST /api/undo/tok-1': { undone: 1, transaction: GREEN } });
    wrapBook(<Review />);
    fireEvent.click(within(await ready(1)).getByRole('button', { name: 'Groceries' }));
    fireEvent.click(within(top()).getByRole('button', { name: 'Undo' }));
    expect(callsTo(fetchMock, 'POST', '/api/undo/')).toHaveLength(0);
    act(() => { answer(reply(SORTED(GREEN, 'groceries'))); });
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/undo/tok-1')).toHaveLength(1));
    await waitFor(() => expect(slots()[0]).toBe('1:card'));
  });

  it('the page scrolls by the height the card lost, so the rows below stay where they were on screen', async () => {
    stubFetch({ ...inList(), '/api/review': Q(ROWS), 'PATCH /api/transactions/2': SORTED(T(2), 'groceries') });
    // One column: each card 300 tall from y=0; a slim row is 56 tall.
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      const els = [...document.querySelectorAll<HTMLElement>('.rcards > [data-id]')];
      const i = els.indexOf(this);
      if (i < 0) return { top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0, x: 0, y: 0, toJSON() {} } as DOMRect;
      const h = (el: HTMLElement) => (el.dataset.testid === 'slim-row' ? 56 : 300);
      const y = els.slice(0, i).reduce((s, el) => s + h(el) + 12, 0);
      return { top: y, bottom: y + h(this), left: 0, right: 0, width: 360, height: h(this), x: 0, y, toJSON() {} } as DOMRect;
    });
    const scrollBy = vi.fn();
    vi.stubGlobal('scrollBy', scrollBy);
    wrapBook(<Review />);
    fireEvent.click(within(await ready(2)).getByRole('button', { name: 'Groceries' }));
    await waitFor(() => slim(2));
    expect(scrollBy).toHaveBeenLastCalledWith(0, -244);          // card 3's top moved from 624 to 380
  });

  it('keys typed into a field do nothing: Z in the Also box sends no Undo', async () => {
    const fetchMock = stubFetch({ ...inList(), '/api/review': Q(ROWS), 'PATCH /api/transactions/2': SORTED(T(2), 'groceries') });
    wrapBook(<Review />);
    fireEvent.click(within(await ready(2)).getByRole('button', { name: 'Groceries' }));
    await waitFor(() => slim(2));
    fireEvent.keyDown(within(card(1)).getByRole('checkbox'), { key: 'z' });
    expect(callsTo(fetchMock, 'POST', '/api/undo/')).toHaveLength(0);
  });

  it('leaving Review clears the slim rows and the stack', async () => {
    stubFetch({ ...inList(), '/api/review': Q(ROWS), 'PATCH /api/transactions/2': SORTED(T(2), 'groceries') });
    const first = wrapBook(<Review />);
    fireEvent.click(within(await ready(2)).getByRole('button', { name: 'Groceries' }));
    await waitFor(() => slim(2));
    first.unmount();
    wrapBook(<Review />);
    await screen.findAllByTestId('review-card');
    expect(screen.queryByTestId('slim-row')).toBeNull();
    expect(within(top()).getByRole('button', { name: 'Undo' })).toBeDisabled();
  });

  it("a repayment's toast adds its facts and Settle", async () => {
    const DEP = T(8, { raw_description: 'ACME CORP EXP', amount_cents: 33965 });
    stubFetch({ ...inList(), '/api/review': Q([DEP], { top_categories: ['reimbursement'] }), '/api/reimburse/payers': { payers: [{ id: 1, name: 'Acme' }] },
      'PATCH /api/transactions/8': SORTED(DEP, 'reimbursement', [], { change: 'repaid', reimburser_id: 1, payer: 'Acme', was_cents: 40000, owed_cents: 6035 }) });
    const { qc } = wrapBook(<Review />);
    await waitFor(() => expect(qc.getQueryData(['reimburse', 'payers'])).toBeDefined());
    fireEvent.click(within(await screen.findByTestId('review-card')).getByRole('button', { name: 'Reimbursement' }));
    await waitFor(() => expect(toast()).toHaveTextContent('SORTED · ACME CORP EXP → Reimbursement Reimbursement from Acme. Acme now owes you $60.35. Settle · Undo'));
    expect(within(toast() as HTMLElement).getByRole('link', { name: 'Settle' })).toHaveAttribute('href', '/b/ours/spending/reimbursements?settle=1');
  });

  it('a viewer sees the list and what is left, with no Undo', async () => {
    stubFetch({ ...inList(), '/api/review': Q(ROWS) });
    wrapBook(<Review />, { role: 'viewer' });
    expect(await screen.findByTestId('review-top')).toHaveTextContent('4 left');
    expect(within(top()).queryByRole('button', { name: 'Undo' })).toBeNull();
    expect(screen.getAllByTestId('review-card')).toHaveLength(4);
  });
});
