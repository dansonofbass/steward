import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LabelView, Txn } from '../../../api/types';
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
const ROWS = [GREEN, T(2, { guess: 'dining', reason: 'unsure' }), T(3), T(4)];
const Q = { uncategorized: ROWS, count: 4, duplicates: [], duplicate_count: 0,
  top_categories: ['groceries', 'dining', 'shopping', 'personal', 'transport'], business: [], business_count: 0 };
const SORTED = (t: Txn, category: string) => ({ ...t, category, result: { category, applied: 0, ids: [], rule: 'made', undo: `tok-${t.id}` } });
const VIEW: LabelView = { nickname: null, reach: { others: 11, payee: 'GREENLEAF MARKET', amount_cents: null, generic: false }, rule: null };
const current = () => screen.getAllByTestId('focus-card').find((c) => c.dataset.role === 'current')!;
const key = (k: string, init: object = {}, at: Element = document.body) => { fireEvent.keyDown(at, { key: k, ...init }); };
const writes = (fetchMock: ReturnType<typeof stubFetch>) => fetchMock.mock.calls.filter(([, i]) => ((i as RequestInit | undefined)?.method ?? 'GET') !== 'GET');
const fine = () => vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('hover: hover') || q.includes('pointer: fine'), media: q, addEventListener: () => {}, removeEventListener: () => {} }));

describe('Focus keys (review focus, Keyboard and focus)', () => {
  it('Enter takes the guess; a held Enter sorts once (Review Focus 3)', async () => {
    const fetchMock = stubFetch({ '/api/review': Q, 'PATCH /api/transactions/1': SORTED(GREEN, 'groceries'), 'PATCH /api/transactions/2': SORTED(ROWS[1], 'dining') });
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    key('Enter');
    key('Enter', { repeat: true });
    key('Enter', { repeat: true });
    await waitFor(() => expect(current().dataset.id).toBe('2'));
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/')).toHaveLength(1);
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/1')[0].body).toEqual({ category: 'groceries', apply_to_matching: true });
  });

  it('"3" picks the third chip; "/" opens all categories with the search focused and empty', async () => {
    const fetchMock = stubFetch({ '/api/review': Q, 'PATCH /api/transactions/1': SORTED(GREEN, 'shopping') });
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    key('/');
    const search = within(screen.getByRole('dialog', { name: 'Category' })).getByRole('combobox', { name: 'Find a category' });
    expect(document.activeElement).toBe(search);
    expect(search).toHaveValue('');
    key('Escape', {}, search);
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Category' })).toBeNull());
    key('3');
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/transactions/1')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/1')[0].body).toMatchObject({ category: 'shopping' });
  });

  it('S snoozes, I ignores, and B shows the Business tag and goes with the next sort', async () => {
    const fetchMock = stubFetch({ '/api/review': Q, 'POST /api/review/1/snooze': { undo: 'tok-1', until: '2026-11-06' },
      'POST /api/review/2/ignore': { undo: 'tok-2' }, 'PATCH /api/transactions/3': SORTED(ROWS[2], 'groceries') });
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    key('s');
    await waitFor(() => expect(current().dataset.id).toBe('2'));
    key('I');
    await waitFor(() => expect(current().dataset.id).toBe('3'));
    expect(document.querySelector('.undo-toast')).toHaveTextContent('Ignored · SHOP 2 · Undo');
    key('b');
    expect(within(current()).getByText('Business')).toHaveClass('tag');
    key('1');
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/transactions/3')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/3')[0].body).toEqual({ category: 'groceries', is_business: true });
  });

  it('N puts focus in the note box; Enter saves without sorting; Shift+Enter is a new line; Esc closes it and focus is back on the card', async () => {
    // Saving shows the card's notes, so the signed-in person (as the app always has) and the notes route are here.
    const fetchMock = stubFetch({ '/api/auth/me': ME, '/api/review': Q, '/api/transactions/1/label': VIEW, '/api/transactions/1/notes': { notes: [] },
      'PUT /api/transactions/1/label': { rows: 12, notes_added: 12, named: 0, rule_id: null, undo: 'tok-n' } });
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    key('n');
    const note = await screen.findByRole('textbox', { name: 'Note' });
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Note' }));
    fireEvent.change(note, { target: { value: 'Asked Sam' } });
    key('Enter', { shiftKey: true }, note);
    expect(callsTo(fetchMock, 'PUT', '/api/transactions/1/label')).toHaveLength(0);
    key('Enter', {}, note);
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/transactions/1/label')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/')).toHaveLength(0);          // a note never sorts the card
    await waitFor(() => expect(document.activeElement).toBe(current()));
    expect(current().dataset.id).toBe('1');
    expect(document.querySelector('.undo-toast')).toHaveTextContent('Saved on 12 · Undo');
    key('N');
    const again = await screen.findByRole('textbox', { name: 'Note' });
    await waitFor(() => expect(document.activeElement).toBe(again));
    fireEvent.change(again, { target: { value: 'draft' } });
    key('Escape', {}, again);
    await waitFor(() => expect(screen.queryByRole('textbox', { name: 'Note' })).toBeNull());
    expect(document.activeElement).toBe(current());
    key('n');
    expect(await screen.findByRole('textbox', { name: 'Note' })).toHaveValue('draft');   // kept until the card changes
  });

  it('keys never fire while typing: s, i and z in the note box, the Name field or the menu’s search send nothing', async () => {
    const fetchMock = stubFetch({ '/api/review': Q, '/api/transactions/1/label': VIEW });
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    key('n');
    const note = await screen.findByRole('textbox', { name: 'Note' });
    for (const k of ['s', 'i', 'z', 'b', '1']) { key(k, {}, note); key(k, {}, screen.getByRole('textbox', { name: 'Name' })); }
    key('Escape', {}, note);
    key('/');
    const search = screen.getByRole('combobox', { name: 'Find a category' });
    for (const k of ['s', 'i', 'z']) key(k, {}, search);
    expect(writes(fetchMock)).toEqual([]);
    expect(screen.getByRole('dialog', { name: 'Category' })).toBeInTheDocument();
  });

  it('keys pressed while an action is in flight are dropped', async () => {
    let answer!: (r: Response) => void;
    const fetchMock = stubFetch({ '/api/review': Q, 'PATCH /api/transactions/1': () => new Promise<Response>((res) => { answer = res; }) });
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    key('Enter');
    key('s');
    key('2');
    expect(writes(fetchMock)).toHaveLength(1);
    act(() => { answer(reply(SORTED(GREEN, 'groceries'))); });
    await waitFor(() => expect(current().dataset.id).toBe('2'));
    expect(writes(fetchMock)).toHaveLength(1);
  });

  it('the ⋯ menu: ↓ opens it on the first item, arrows move, Esc gives focus back; Business is a checkbox; Ignore ignores', async () => {
    stubFetch({ '/api/review': Q, 'POST /api/review/1/ignore': { undo: 'tok-1' } });
    wrapBook(<Review />);
    await screen.findByTestId('focus-bar');
    const dots = within(current()).getByRole('button', { name: 'More actions' });
    expect(dots).toHaveAttribute('aria-haspopup', 'menu');
    key('ArrowDown', {}, dots);
    const menu = screen.getByRole('menu', { name: 'More actions' });
    expect([...menu.querySelectorAll('[role^="menuitem"]')].map((m) => m.textContent)).toEqual(['Ignore', 'Business', 'Reimbursable', 'Add note']);
    expect(document.activeElement).toBe(within(menu).getByRole('menuitem', { name: 'Ignore' }));
    key('ArrowDown', {}, document.activeElement!);
    expect(document.activeElement).toBe(within(menu).getByRole('menuitemcheckbox', { name: 'Business' }));
    key('s', {}, document.activeElement!);                                // a menu is open: no Snooze
    key('Escape', {}, document.activeElement!);
    expect(screen.queryByRole('menu')).toBeNull();
    expect(document.activeElement).toBe(dots);
    fireEvent.click(dots);
    fireEvent.click(screen.getByRole('menuitemcheckbox', { name: 'Business' }));
    expect(within(current()).getByText('Business')).toHaveClass('tag');
    fireEvent.click(dots);
    expect(screen.getByRole('menuitemcheckbox', { name: 'Business' })).toHaveAttribute('aria-checked', 'true');
    fireEvent.click(screen.getByRole('menuitem', { name: 'Ignore' }));
    await waitFor(() => expect(current().dataset.id).toBe('2'));
    expect(document.querySelector('.undo-toast')).toHaveTextContent('Ignored · GREENLEAF MARKET · Undo');
  });

  it('on a fine pointer the keys line names the guess, and every control carries its key', async () => {
    fine();
    stubFetch({ '/api/review': Q });
    wrapBook(<Review />);
    const bar = await screen.findByTestId('focus-bar');
    expect(screen.getByTestId('focus-keys')).toHaveTextContent('Enter Groceries · 1–4 pick · S snooze · I ignore · B business · Z undo · N note');
    expect(screen.getByTestId('focus-keys')).toHaveAttribute('aria-hidden', 'true');
    expect(within(current()).getByRole('button', { name: 'Groceries' })).toHaveAttribute('aria-keyshortcuts', '1');
    expect(within(bar).getAllByRole('button')[1]).toHaveAttribute('aria-keyshortcuts', 'Enter');
    expect(within(screen.getByTestId('review-top')).getByRole('button', { name: 'Undo' })).toHaveAttribute('aria-keyshortcuts', 'Z');
  });
});
