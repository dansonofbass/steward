import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LabelView, Note, Txn } from '../api/types';
import { callsTo, inList, ME, reply, stubFetch, wrapBook } from '../test-utils';
import Review from './Review';

beforeEach(() => { localStorage.clear(); localStorage.setItem('steward-celebrations', 'off'); vi.spyOn(Math, 'random').mockReturnValue(0.5); });
afterEach(() => { vi.restoreAllMocks(); });

const T = (id: number, extra: Partial<Txn> = {}): Txn => ({
  id, account_id: 1, account_name: 'Checking', posted_at: '2026-10-10', amount_cents: -1200, raw_description: `SHOP ${id}`,
  merchant: null, category: 'uncategorized', is_business: false, is_transfer: false, business_pct: 0, business_line: null,
  business_source: 'none', category_source: 'none', reviewed_at: null, from_bank: true, note_count: 0, reason: 'unknown',
  guess: null, matching: 0, reimburse_ok: false, ...extra,
});
const ROWS = [T(1, { raw_description: 'GREENLEAF MARKET' }), T(2)];
const Q = { uncategorized: ROWS, count: 2, duplicates: [], duplicate_count: 0, top_categories: ['groceries', 'dining'], business: [], business_count: 0 };
const VIEW: LabelView = { nickname: null, reach: null, rule: null };
const NOTE: Note = { id: 9, author_id: 1, author_name: 'JR', body: 'Asked Sam about this one', created_at: '2026-10-13T18:00:00+00:00' };
const LINE = /^JR, .+: Asked Sam about this one/;

/** The row's notes as the server keeps them: none, then the saved one, then none again after Undo. */
function server(more: Record<string, unknown> = {}) {
  let notes: Note[] = [];
  return stubFetch({
    '/api/auth/me': ME, '/api/review': Q, '/api/transactions/1/label': VIEW,
    '/api/transactions/1/notes': () => reply({ notes }),
    'PUT /api/transactions/1/label': () => { notes = [NOTE]; return reply({ rows: 1, notes_added: 1, named: 0, rule_id: null, undo: 'tok-n' }); },
    'POST /api/undo/tok-n': () => { notes = []; return reply({ undone: 1, transaction: null }); },
    ...more,
  });
}
const toasts = () => [...document.querySelectorAll<HTMLElement>('.undo-toast')];

describe('a Review card shows notes written elsewhere, from the row’s note_count, with no save', () => {
  const TWO = { notes: [
    { id: 1, author_id: 2, author_name: 'Sam', body: 'Paid my half in cash', created_at: '2026-10-11T18:00:00+00:00' },
    { id: 2, author_id: 1, author_name: 'JR', body: 'Water heater', created_at: '2026-10-12T18:00:00+00:00' },
  ] };
  const withNotes = { ...Q, uncategorized: [{ ...ROWS[0], note_count: 2 }, ROWS[1]] };
  const lines = (el: HTMLElement) => [...el.querySelectorAll('.notes__list li')].map((li) => li.textContent);

  it('list: the card with notes shows both lines; the one without asks for none', async () => {
    const fetchMock = stubFetch({ ...inList(), '/api/review': withNotes, '/api/transactions/1/notes': TWO });
    wrapBook(<Review />);
    await screen.findAllByTestId('review-card');
    const card = (id: string) => screen.getAllByTestId('review-card').find((c) => c.dataset.id === id)!;
    await waitFor(() => expect(lines(card('1'))).toHaveLength(2));
    expect(lines(card('1'))[0]).toMatch(/^Sam, .+: Paid my half in cash$/);
    expect(lines(card('1'))[1]).toMatch(/^JR, .+: Water heaterRemove$/);
    expect(callsTo(fetchMock, 'GET', '/api/transactions/2/notes')).toHaveLength(0);
    expect(screen.queryByTestId('note-form')).toBeNull();
  });

  it('focus: the current card shows both lines', async () => {
    stubFetch({ '/api/auth/me': ME, '/api/review': withNotes, '/api/transactions/1/notes': TWO });
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    const current = () => screen.getAllByTestId('focus-card').find((c) => c.dataset.role === 'current')!;
    await waitFor(() => expect(lines(current())).toHaveLength(2));
    expect(lines(current())[0]).toMatch(/^Sam, .+: Paid my half in cash$/);
  });
});

describe('removing a note on a Review card goes on Review’s toast, with Undo', () => {
  const SAM = { id: 1, author_id: 2, author_name: 'Sam', body: 'Paid my half in cash', created_at: '2026-10-11T18:00:00+00:00' };
  const MINE = { id: 2, author_id: 1, author_name: 'JR', body: 'Water heater', created_at: '2026-10-12T18:00:00+00:00' };
  const withNotes = { ...Q, uncategorized: [{ ...ROWS[0], note_count: 2 }, ROWS[1]] };
  const lines = (el: HTMLElement) => [...el.querySelectorAll('.notes__list li')].map((li) => li.textContent?.replace(/^(\w+), .+?: /, '$1: '));
  function notesServer(more: Record<string, unknown> = {}) {
    let notes = [SAM, MINE];
    return stubFetch({
      '/api/auth/me': ME, '/api/review': withNotes, '/api/transactions/1/notes': () => reply({ notes }),
      'DELETE /api/transactions/1/notes/2': () => { notes = [SAM]; return reply({ undo: 'tok-rm' }); },
      'POST /api/undo/tok-rm': () => { notes = [SAM, MINE]; return reply({ undone: 1, transaction: null }); },
      ...more,
    });
  }
  async function removeAndUndo(card: () => HTMLElement, fetchMock: ReturnType<typeof stubFetch>, focused?: () => HTMLElement) {
    await waitFor(() => expect(lines(card())).toEqual(['Sam: Paid my half in cash', 'JR: Water heaterRemove']));
    fireEvent.click(within(card()).getByRole('button', { name: /^Remove note from / }));
    expect(lines(card())).toEqual(['Sam: Paid my half in cash']);                    // hidden at once
    await waitFor(() => expect(toasts()).toHaveLength(1));                          // Review's one toast
    if (focused) expect(document.activeElement).toBe(focused());                   // not lost with the button
    expect(toasts()[0]).toHaveTextContent('Removed · Undo');
    fireEvent.click(within(toasts()[0]).getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(lines(card())).toEqual(['Sam: Paid my half in cash', 'JR: Water heaterRemove']));   // back in its place
    expect(callsTo(fetchMock, 'POST', '/api/undo/tok-rm')).toHaveLength(1);
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/')).toHaveLength(0);
  }

  it('list: and focus goes to the card’s Note', async () => {
    const fetchMock = notesServer(inList());
    wrapBook(<Review />);
    await screen.findAllByTestId('review-card');
    const card = () => screen.getAllByTestId('review-card').find((c) => c.dataset.id === '1')!;
    await removeAndUndo(card, fetchMock, () => within(card()).getByRole('button', { name: 'Note' }));
  });

  it('focus: and focus goes back to the card', async () => {
    const fetchMock = notesServer();
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    const current = () => screen.getAllByTestId('focus-card').find((c) => c.dataset.role === 'current')!;
    await waitFor(() => expect(lines(current())).toHaveLength(2));
    within(current()).getByRole('button', { name: /^Remove note from / }).focus();
    await removeAndUndo(current, fetchMock, current);
    expect(current().dataset.id).toBe('1');
  });
});

describe('a note saved from a Review card shows on the card at once, with Review’s Undo', () => {
  it('list: saving closes the form, the line appears, Review’s toast says Saved, and its Undo takes the line away', async () => {
    const fetchMock = server(inList());
    wrapBook(<Review />);
    const card = () => screen.getAllByTestId('review-card').find((c) => c.dataset.id === '1')!;
    await screen.findAllByTestId('review-card');
    fireEvent.click(within(card()).getByRole('button', { name: 'Note' }));
    fireEvent.change(await within(card()).findByLabelText('Note'), { target: { value: 'Asked Sam about this one' } });
    fireEvent.click(within(card()).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(within(card()).queryByTestId('note-form')).toBeNull());
    expect(await within(card()).findByText((_, el) => el?.tagName === 'LI' && LINE.test(el.textContent ?? ''))).toBeInTheDocument();
    expect(toasts()).toHaveLength(1);                                       // Review's own, not a second one in the form
    expect(toasts()[0]).toHaveTextContent('Saved · Undo');
    expect(document.activeElement).toBe(within(card()).getByRole('button', { name: 'Note' }));
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/')).toHaveLength(0);          // a note never sorts it
    fireEvent.click(within(toasts()[0]).getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(card().querySelector('.notes__list')).toBeNull());
    expect(callsTo(fetchMock, 'POST', '/api/undo/tok-n')).toHaveLength(1);
    expect(screen.getAllByTestId('review-card').map((c) => c.dataset.id)).toEqual(['1', '2']);   // the card stays put
  });

  it('focus: saving closes the box, the line appears on the card, focus is on the card, and Undo takes it away', async () => {
    const fetchMock = server();
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    const current = () => screen.getAllByTestId('focus-card').find((c) => c.dataset.role === 'current')!;
    fireEvent.click(within(current()).getByRole('button', { name: 'More actions' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Add note' }));
    fireEvent.change(await within(current()).findByRole('textbox', { name: 'Note' }), { target: { value: 'Asked Sam about this one' } });
    fireEvent.click(within(current()).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(within(current()).queryByRole('textbox', { name: 'Note' })).toBeNull());
    expect(await within(current()).findByText((_, el) => el?.tagName === 'LI' && LINE.test(el.textContent ?? ''))).toBeInTheDocument();
    expect(document.activeElement).toBe(current());
    expect(current().dataset.id).toBe('1');
    expect(toasts()).toHaveLength(1);
    expect(toasts()[0]).toHaveTextContent('Saved · Undo');
    fireEvent.click(within(toasts()[0]).getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(current().querySelector('.notes__list')).toBeNull());
    expect(callsTo(fetchMock, 'POST', '/api/undo/tok-n')).toHaveLength(1);
    expect(current().dataset.id).toBe('1');
  });
});
