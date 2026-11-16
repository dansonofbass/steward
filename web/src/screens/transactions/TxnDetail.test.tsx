import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Txn } from '../../api/types';
import { AskHost } from '../../ask/AskHost';
import { askState, resetAsk } from '../../ask/store';
import { resetTourLoad } from '../../lib/askTour';
import { callsTo, reply, stubFetch, wrapBook } from '../../test-utils';
import { Sheet } from '../../ui/Sheet';
import { ME, STATUS, DINING_REPLY } from '../chat/panel/fixtures';
import { LIST } from '../spending/setasides/fixtures';
import { TxnDetail } from './TxnDetail';

afterEach(() => vi.unstubAllGlobals());

const TXN: Txn = {
  id: 7, account_id: 1, account_name: 'Rewards Card', posted_at: '2026-10-03', amount_cents: -10000,
  raw_description: 'MOBILE ONE WIRELESS', merchant: 'Mobile One', category: 'utilities', is_business: false,
  is_transfer: false, business_pct: 0, business_line: null, business_source: 'none', category_source: 'rule',
  reviewed_at: null, from_bank: true, set_aside: null,
};
const today = new Date(2026, 9, 13);
/** The detail's own Save: the household note form above it has one too. */
const detailSave = () => screen.getAllByRole('button', { name: 'Save' }).find((b) => !b.closest('[data-testid="note-form"]'))!;
const open = (txn: Txn, book = {}) =>
  wrapBook(<TxnDetail txn={txn} today={today} onSaved={() => {}} onClose={() => {}} showHeader={false} />, book);

describe('a named row (polish round P5)', () => {
  it('titles the detail "Disney+ (PayPal)"', () => {
    wrapBook(<TxnDetail txn={{ ...TXN, merchant: 'PayPal', nickname: 'Disney+' }} today={today} onSaved={() => {}} onClose={() => {}} showHeader />);
    expect(screen.getByRole('heading', { name: 'Disney+ (PayPal)' })).toBeInTheDocument();
  });
});

describe('one filled Save in the detail (final review)', () => {
  it("the note form's Save is quiet, so the nearest filled Save is the detail's own", async () => {
    stubFetch({ '/api/transactions/7/label': { nickname: null, reach: null, rule: null } });
    open(TXN);
    const noteSave = await waitFor(() => within(screen.getByTestId('note-form')).getByRole('button', { name: 'Save' }));
    expect(noteSave).toHaveClass('btn--quiet');
    expect(noteSave).not.toHaveClass('btn--primary');
    expect(detailSave()).toHaveClass('btn--primary');
  });
});

describe('Business or personal on a transaction', () => {
  it('saves a split with its line and a rule, without touching the category', async () => {
    const fetchMock = stubFetch({
      'PUT /api/business/transactions/7': { ...TXN, business_pct: 40, business_line: 'utilities', business_source: 'manual' },
      'POST /api/business/rules': { rule: { id: 3, kind: 'merchant', label: 'Mobile One', account_id: 1, account_name: 'Rewards Card', pct: 40, line: 'utilities' }, also_tagged: 2 },
    });
    open(TXN);
    fireEvent.click(screen.getByRole('radio', { name: 'Split' }));
    fireEvent.change(screen.getByLabelText('Business share'), { target: { value: '40' } });
    fireEvent.change(screen.getByLabelText('Schedule C line'), { target: { value: 'utilities' } });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Always for Mobile One on Rewards Card' }));
    fireEvent.click(detailSave());
    await screen.findByText('Saved. Tagged 2 earlier transactions too.');
    expect(callsTo(fetchMock, 'PUT', '/api/business/transactions/7')[0].body).toEqual({ pct: 40, line: 'utilities' });
    expect(callsTo(fetchMock, 'POST', '/api/business/rules')[0].body).toEqual({ kind: 'merchant', transaction_id: 7, pct: 40, line: 'utilities' });
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/7')).toHaveLength(0);
  });

  it('refuses a split share outside 1 to 99', () => {
    stubFetch({});
    open(TXN);
    fireEvent.click(screen.getByRole('radio', { name: 'Split' }));
    fireEvent.change(screen.getByLabelText('Business share'), { target: { value: '100' } });
    expect(screen.getByText('Enter a whole percent from 1 to 99.')).toBeInTheDocument();
    expect(detailSave()).toBeDisabled();
  });

  it('offers a client rule for money in', async () => {
    const fetchMock = stubFetch({
      'PUT /api/business/transactions/8': { ...TXN, id: 8, amount_cents: 300000, business_pct: 100, is_business: true },
      'POST /api/business/rules': { rule: { id: 4, kind: 'client', label: 'ACH CLIENT INV', account_id: null, account_name: null, pct: 100, line: null }, also_tagged: 0 },
    });
    open({ ...TXN, id: 8, amount_cents: 300000, merchant: null, raw_description: 'ACH CLIENT INV 4821', category: 'business_income' });
    fireEvent.click(screen.getByRole('radio', { name: 'Business' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'ACH CLIENT INV 4821 is a client' }));
    fireEvent.click(detailSave());
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/business/rules')).toHaveLength(1));
    expect(callsTo(fetchMock, 'POST', '/api/business/rules')[0].body).toEqual({ kind: 'client', transaction_id: 8, pct: 100, line: 'income' });
    expect(callsTo(fetchMock, 'PUT', '/api/business/transactions/8')[0].body).toEqual({ pct: 100, line: 'income' });
  });

  it('a client is all business: ticking it with Split chosen switches to Business (final review M5)', async () => {
    const fetchMock = stubFetch({
      'PUT /api/business/transactions/8': { ...TXN, id: 8, amount_cents: 300000, business_pct: 100, is_business: true },
      'POST /api/business/rules': { rule: { id: 4, kind: 'client', label: 'ACH CLIENT INV', account_id: null, account_name: null, pct: 100, line: 'income' }, also_tagged: 0 },
    });
    open({ ...TXN, id: 8, amount_cents: 300000, merchant: null, raw_description: 'ACH CLIENT INV 4821', category: 'business_income' });
    fireEvent.click(screen.getByRole('radio', { name: 'Split' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'ACH CLIENT INV 4821 is a client' }));
    expect(screen.getByRole('radio', { name: 'Business' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.queryByLabelText('Business share')).toBeNull();
    fireEvent.click(screen.getByRole('radio', { name: 'Split' }));
    expect(screen.getByRole('checkbox', { name: 'ACH CLIENT INV 4821 is a client' })).not.toBeChecked();
    fireEvent.click(screen.getByRole('checkbox', { name: 'ACH CLIENT INV 4821 is a client' }));
    fireEvent.click(detailSave());
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/business/rules')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PUT', '/api/business/transactions/8')[0].body).toEqual({ pct: 100, line: 'income' });
  });

  it('a tag refreshes Spending, the strip on Home and the plan too (final review M4)', async () => {
    stubFetch({ 'PUT /api/business/transactions/7': { ...TXN, business_pct: 100, is_business: true, business_source: 'manual' } });
    const { qc } = open(TXN);
    const spy = vi.spyOn(qc, 'invalidateQueries');
    fireEvent.click(screen.getByRole('radio', { name: 'Business' }));
    fireEvent.click(detailSave());
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['spending'] }));   // Spending and Home's strip
    expect(spy).toHaveBeenCalledWith({ queryKey: ['plan'] });
  });

  it('shows no business control in a parent book or on a transfer', () => {
    stubFetch({});
    const { unmount } = open(TXN, { slug: 'mom', kind: 'parent' });
    expect(screen.queryByRole('radiogroup', { name: 'Business or personal' })).toBeNull();
    unmount();
    open({ ...TXN, is_transfer: true, category: 'transfer' });
    expect(screen.queryByRole('radiogroup', { name: 'Business or personal' })).toBeNull();
  });
});

describe('Paid from a set-aside, in the detail', () => {
  it('offers the control for money out in the household book', () => {
    stubFetch({ '/api/setasides': { ...LIST } });
    open(TXN);
    expect(screen.getByRole('button', { name: 'Paid from a set-aside' })).toBeInTheDocument();
  });
});

describe('the matching box, the facts and Undo after Save (sorting redesign, The transaction detail)', () => {
  const pick = (name: string) => {
    fireEvent.click(screen.getByRole('button', { name: /^Category / }));
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Category' })).getByRole('option', { name }));
  };
  // The category is bold, so no element's own text holds the whole sentence: match the facts element's full text (preflight F1).
  const facts = (s: string) => (_: string, el: Element | null) => !!el?.matches('.detail__receipt') && el.textContent === s;
  const RESULT = { category: 'home', applied: 3, rule: 'changed', undo: 'tok' } as const;

  it('offers the matching rows once the category changes, ticked, and says what Save did', async () => {
    const fetchMock = stubFetch({
      '/api/transactions/7/matching': { count: 3 },
      'PATCH /api/transactions/7': { ...TXN, category: 'home', result: RESULT },
      '/api/transactions/7/notes': { notes: [] },
    });
    open(TXN);
    expect(screen.queryByRole('checkbox', { name: /^Also apply/ })).toBeNull();
    pick('Home and garden');
    expect(await screen.findByRole('checkbox', { name: 'Also apply to 3 matching transactions' })).toBeChecked();
    fireEvent.click(detailSave());
    expect(await screen.findByText(facts('Home and garden for Mobile One, and for the 3 matching ones. New matching transactions will be categorized automatically.'))).toBeInTheDocument();
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/7')[0].body).toEqual({ category: 'home', apply_to_matching: true });
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument();
  });

  it('unticked, it changes this row only and says so', async () => {
    const fetchMock = stubFetch({
      '/api/transactions/7/matching': { count: 3 },
      'PATCH /api/transactions/7': { ...TXN, category: 'home', result: { ...RESULT, applied: 0 } },
      '/api/transactions/7/notes': { notes: [] },
    });
    open(TXN);
    pick('Home and garden');
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Also apply to 3 matching transactions' }));
    fireEvent.click(detailSave());
    expect(await screen.findByText(facts('Home and garden for this one only.'))).toBeInTheDocument();
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/7')[0].body).toEqual({ category: 'home', apply_to_matching: false });
  });

  it('Undo puts the row back and says Undone.', async () => {
    const fetchMock = stubFetch({
      '/api/transactions/7/matching': { count: 0 },
      'PATCH /api/transactions/7': { ...TXN, category: 'home', result: { ...RESULT, applied: 0, rule: 'made' } },
      'POST /api/undo/tok': { undone: 1, transaction: TXN },
      '/api/transactions/7/notes': { notes: [] },
    });
    open(TXN);
    pick('Home and garden');
    fireEvent.click(detailSave());
    expect(await screen.findByText(facts('Home and garden for Mobile One. Steward will remember this for next time.'))).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(await screen.findByText('Undone.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/undo/tok')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Category Utilities' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull();
  });

  it('a refused Undo shows the sentence from the server and drops the button', async () => {
    stubFetch({
      '/api/transactions/7/matching': { count: 0 },
      'PATCH /api/transactions/7': { ...TXN, category: 'home', result: { ...RESULT, applied: 0 } },
      'POST /api/undo/tok': () => reply({ error: "That changed since, so it can't be undone." }, 409),
      '/api/transactions/7/notes': { notes: [] },
    });
    open(TXN);
    pick('Home and garden');
    fireEvent.click(detailSave());
    fireEvent.click(await screen.findByRole('button', { name: 'Undo' }));
    expect(await screen.findByText("That changed since, so it can't be undone.")).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull();
  });

  it('a merchant-only save says Saved. with no box and no Undo', async () => {
    stubFetch({ 'PATCH /api/transactions/7': { ...TXN, merchant: 'Mobile 1' }, '/api/transactions/7/notes': { notes: [] } });
    open(TXN);
    fireEvent.change(screen.getByLabelText('Merchant'), { target: { value: 'Mobile 1' } });
    fireEvent.click(detailSave());
    expect(await screen.findByText('Saved.')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: /^Also apply/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull();
  });

  it("in the phone's sheet, a saved merchant asks nothing on Close; a refused one still asks (16i review I-2)", async () => {
    let refuse = false;
    stubFetch({ 'PATCH /api/transactions/7': () => (refuse ? reply({ error: 'No.' }, 400) : reply({ ...TXN, merchant: 'Mobile 1' })),
      '/api/transactions/7/notes': { notes: [] }, '/api/transactions/7/label': { nickname: null, reach: null, rule: null } });
    const closeTxn = vi.fn();
    const view = wrapBook(<Sheet open onClose={closeTxn} title="Mobile One"><TxnDetail txn={TXN} today={today} onSaved={() => {}} onClose={closeTxn} showHeader={false} /></Sheet>);
    const box = screen.getByLabelText('Merchant');
    box.focus();
    fireEvent.change(box, { target: { value: 'Mobile 1' } });
    fireEvent.click(detailSave());
    expect(await screen.findByText('Saved.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByText('Discard what you typed?')).toBeNull();
    expect(closeTxn).toHaveBeenCalledOnce();
    view.unmount();
    refuse = true;
    wrapBook(<Sheet open onClose={closeTxn} title="Mobile One"><TxnDetail txn={TXN} today={today} onSaved={() => {}} onClose={closeTxn} showHeader={false} /></Sheet>);
    const again = screen.getByLabelText('Merchant');
    again.focus();
    fireEvent.change(again, { target: { value: 'Mobile 2' } });
    fireEvent.click(detailSave());
    expect(await screen.findByText(/No\./)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.getByText('Discard what you typed?')).toBeInTheDocument();
    expect(closeTxn).toHaveBeenCalledOnce();
  });

  it("a saved merchant doesn't take the note typed above it as saved (16i re-review R-1)", async () => {
    stubFetch({ 'PATCH /api/transactions/7': { ...TXN, merchant: 'Mobile 1' }, '/api/transactions/7/notes': { notes: [] },
      '/api/transactions/7/label': { nickname: null, reach: null, rule: null } });
    const closeTxn = vi.fn();
    wrapBook(<Sheet open onClose={closeTxn} title="Mobile One"><TxnDetail txn={TXN} today={today} onSaved={() => {}} onClose={closeTxn} showHeader={false} /></Sheet>);
    const note = await screen.findByLabelText('Note');
    note.focus();
    fireEvent.change(note, { target: { value: 'Ask Sam about this' } });
    const box = screen.getByLabelText('Merchant');
    box.focus();
    fireEvent.change(box, { target: { value: 'Mobile 1' } });
    fireEvent.click(detailSave());
    expect(await screen.findByText('Saved.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.getByText('Discard what you typed?')).toBeInTheDocument();
    expect(closeTxn).not.toHaveBeenCalled();
  });
});

describe('Ask about this on a transaction (Surfaces, P20)', () => {
  afterEach(() => { resetAsk(); localStorage.clear(); resetTourLoad(); });
  it('asks about the row by its id alone, with its category for the suggestions', () => {
    open({ ...TXN, nickname: 'zorblax', note_count: 2 }, { chat: true });
    fireEvent.click(screen.getByRole('button', { name: 'Ask about zorblax (Mobile One)' }));
    expect(askState().about).toStrictEqual({ kind: 'transaction', id: 7 });
    expect(askState().surface).toStrictEqual({ kind: 'transaction', category: 'utilities' });
  });
  it('has no Ask button with chat off', () => {
    open(TXN);
    expect(document.querySelector('.ask-about')).toBeNull();
  });
  it("over the transaction's sheet: one Escape closes Ask, the next closes the transaction", async () => {
    localStorage.setItem('steward-ask-tour:1', 'done');
    stubFetch({ '/api/chat': STATUS, '/api/auth/me': ME, 'POST /api/chat/about': DINING_REPLY,
      '/api/transactions/7/label': { nickname: null, reach: null, rule: null } });
    const closeTxn = vi.fn();
    wrapBook(<><Sheet open onClose={closeTxn} title="Mobile One"><TxnDetail txn={TXN} today={today} onSaved={() => {}} onClose={closeTxn} showHeader={false} /></Sheet><AskHost /></>, { chat: true });
    fireEvent.click(screen.getByRole('button', { name: 'Ask about Mobile One' }));
    expect(await screen.findByRole('dialog', { name: 'Ask' })).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Ask' })).toBeNull());
    expect(closeTxn).not.toHaveBeenCalled();
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(closeTxn).toHaveBeenCalledOnce();
  });
});
