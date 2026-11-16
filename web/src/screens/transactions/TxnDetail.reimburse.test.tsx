import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Txn } from '../../api/types';
import { callsTo, reply, stubFetch, wrapBook } from '../../test-utils';
import { LIST } from '../spending/setasides/fixtures';
import { TxnDetail } from './TxnDetail';

afterEach(() => vi.unstubAllGlobals());

const TXN: Txn = {
  id: 7, account_id: 1, account_name: 'Sapphire', posted_at: '2026-10-07', amount_cents: -41218,
  raw_description: 'HILTON CHICAGO IL', merchant: 'Hilton', category: 'travel', is_business: false, is_transfer: false,
  business_pct: 0, business_line: null, business_source: 'none', category_source: 'rule', reviewed_at: null,
  from_bank: true, set_aside: null, reimburser_id: null, reimburse_ok: true,
};
const ACME = { payers: [{ id: 1, name: 'Acme' }] };
const MARKED = { change: 'marked', reimburser_id: 1, payer: 'Acme', was_cents: 82817, owed_cents: 124035 };
const BASE = { '/api/transactions/7/notes': { notes: [] }, '/api/setasides': LIST };
const open = (txn: Txn) =>
  wrapBook(<TxnDetail txn={txn} today={new Date(2026, 9, 13)} onSaved={() => {}} onClose={() => {}} showHeader={false} />);
const save = () => screen.getAllByRole('button', { name: 'Save' }).find((b) => b.getAttribute('type') === 'submit' && !b.closest('[data-testid="note-form"]'))!;
// The category is bold, so no element's own text holds the whole sentence: match the facts element's full text.
const facts = (s: string) => (_: string, el: Element | null) => !!el?.matches('.detail__receipt') && el.textContent === s;
const pick = (name: string) => {
  fireEvent.click(screen.getByRole('button', { name: /^Category / }));
  fireEvent.click(within(screen.getByRole('dialog', { name: 'Category' })).getByRole('option', { name }));
};

describe('Reimbursable in the transaction detail (reimbursable spec, Marking)', () => {
  it('switch on and Always reimbursable: one PATCH, then the rule, and the facts', async () => {
    const fetchMock = stubFetch({ ...BASE, '/api/reimburse/payers': ACME,
      'PATCH /api/transactions/7': { ...TXN, reimburser_id: 1, result: { category: 'travel', applied: 0, rule: 'none', undo: 'tok', reimburse: MARKED } },
      'POST /api/reimburse/rules': { rule: { id: 3, pattern: 'HILTON CHICAGO IL', reimburser_id: 1 }, also_marked: 3, undo: 'rtok' } });
    open(TXN);
    fireEvent.click(screen.getByRole('switch', { name: 'Reimbursable' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Always reimbursable for “Hilton”' }));
    await waitFor(() => expect(save()).toBeEnabled());
    fireEvent.click(save());
    expect(await screen.findByText(facts('Travel, reimbursable. Acme owes you $412.18 more ($1,240.35 in all). Also marked 3 more.'))).toBeInTheDocument();
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/7')[0].body).toEqual({ reimbursable: true });
    expect(callsTo(fetchMock, 'POST', '/api/reimburse/rules')[0].body).toEqual({ transaction_id: 7 });
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument();
  });

  it('Undo after the Always save reverses the rule first, then the mark', async () => {
    const fetchMock = stubFetch({ ...BASE, '/api/reimburse/payers': ACME,
      'PATCH /api/transactions/7': { ...TXN, reimburser_id: 1, result: { category: 'travel', applied: 0, rule: 'none', undo: 'tok', reimburse: MARKED } },
      'POST /api/reimburse/rules': { rule: { id: 3, pattern: 'HILTON CHICAGO IL', reimburser_id: 1 }, also_marked: 3, undo: 'rtok' },
      'POST /api/undo/rtok': { undone: 4 }, 'POST /api/undo/tok': { undone: 1, transaction: TXN } });
    open(TXN);
    fireEvent.click(screen.getByRole('switch', { name: 'Reimbursable' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Always reimbursable for “Hilton”' }));
    await waitFor(() => expect(save()).toBeEnabled());
    fireEvent.click(save());
    fireEvent.click(await screen.findByRole('button', { name: 'Undo' }));
    expect(await screen.findByText('Undone.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/undo/rtok')).toHaveLength(1);
    expect(callsTo(fetchMock, 'POST', '/api/undo/tok')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull();
  });

  it('with the switch already on, only ticking Always runs no PATCH and still offers the rule\'s Undo', async () => {
    const fetchMock = stubFetch({ ...BASE, '/api/reimburse/payers': ACME,
      'POST /api/reimburse/rules': { rule: { id: 3, pattern: 'HILTON CHICAGO IL', reimburser_id: 1 }, also_marked: 2, undo: 'rtok' },
      'POST /api/undo/rtok': { undone: 3, transaction: { ...TXN, reimburser_id: 1 } } });
    open({ ...TXN, reimburser_id: 1 });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Always reimbursable for “Hilton”' }));
    await waitFor(() => expect(save()).toBeEnabled());
    fireEvent.click(save());
    fireEvent.click(await screen.findByRole('button', { name: 'Undo' }));
    expect(await screen.findByText('Undone.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/7')).toHaveLength(0);
    expect(callsTo(fetchMock, 'POST', '/api/undo/rtok')).toHaveLength(1);
  });

  it('switching it on turns Business off, says why, and sends no business PUT', async () => {
    const fetchMock = stubFetch({ ...BASE, '/api/reimburse/payers': ACME,
      'PATCH /api/transactions/7': { ...TXN, reimburser_id: 1, result: { category: 'travel', applied: 0, rule: 'none', undo: 'tok', reimburse: MARKED } } });
    open({ ...TXN, business_pct: 100, is_business: true, business_source: 'manual' });
    expect(screen.getByRole('radio', { name: 'Business' })).toHaveAttribute('aria-checked', 'true');
    fireEvent.click(screen.getByRole('switch', { name: 'Reimbursable' }));
    expect(screen.getByRole('radio', { name: 'Personal' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByText('A charge is either business or reimbursable.')).toBeInTheDocument();
    await waitFor(() => expect(save()).toBeEnabled());
    fireEvent.click(save());
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/transactions/7')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PUT', '/api/business/transactions/7')).toHaveLength(0);
  });

  it('choosing Business turns Reimbursable off', () => {
    stubFetch({ ...BASE, '/api/reimburse/payers': ACME });
    open({ ...TXN, reimburser_id: 1 });
    expect(screen.getByRole('switch', { name: 'Reimbursable' })).toHaveAttribute('aria-checked', 'true');
    fireEvent.click(screen.getByRole('radio', { name: 'Business' }));
    expect(screen.getByRole('switch', { name: 'Reimbursable' })).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByText('A charge is either business or reimbursable.')).toBeInTheDocument();
  });

  it('switching it off says the charge counts as spending again', async () => {
    const fetchMock = stubFetch({ ...BASE, '/api/reimburse/payers': ACME,
      'PATCH /api/transactions/7': { ...TXN, amount_cents: -1840, result: { category: 'travel', applied: 0, rule: 'none', undo: 'tok',
        reimburse: { change: 'unmarked', reimburser_id: 1, payer: 'Acme', was_cents: 1840, owed_cents: 0 } } } });
    open({ ...TXN, amount_cents: -1840, reimburser_id: 1 });
    fireEvent.click(screen.getByRole('switch', { name: 'Reimbursable' }));
    fireEvent.click(save());
    expect(await screen.findByText(facts('Not reimbursed: $18.40 counts as your spending again.'))).toBeInTheDocument();
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/7')[0].body).toEqual({ reimbursable: false });
  });

  it('a deposit sorted as Reimbursement with no payer yet asks who pays, then saves', async () => {
    let payers: { id: number; name: string }[] = [];
    const deposit: Txn = { ...TXN, id: 7, amount_cents: 33965, raw_description: 'ACME CORP EXP', merchant: null, category: 'uncategorized', reimburse_ok: false };
    const fetchMock = stubFetch({ ...BASE, '/api/transactions/7/matching': { count: 0 },
      '/api/reimburse/payers': () => reply({ payers }),
      'POST /api/reimburse/payers': () => { payers = [{ id: 1, name: 'Acme' }]; return reply(payers[0], 201); },
      'PATCH /api/transactions/7': { ...deposit, category: 'reimbursement', reimburser_id: 1, result: { category: 'reimbursement', applied: 0, rule: 'made', undo: 'tok',
        reimburse: { change: 'repaid', reimburser_id: 1, payer: 'Acme', was_cents: 40000, owed_cents: 6035 } } } });
    open(deposit);
    expect(screen.queryByRole('switch', { name: 'Reimbursable' })).toBeNull();
    pick('Reimbursement');
    const box = await screen.findByPlaceholderText('Your employer, e.g. Acme');
    expect(save()).toBeDisabled();
    fireEvent.change(box, { target: { value: 'Acme' } });
    fireEvent.click(within(screen.getByRole('group', { name: 'Who pays you back?' })).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(screen.queryByPlaceholderText('Your employer, e.g. Acme')).toBeNull());
    await waitFor(() => expect(save()).toBeEnabled());
    fireEvent.click(save());
    expect(await screen.findByText(facts('Reimbursement from Acme. Acme now owes you $60.35.'))).toBeInTheDocument();
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/7')[0].body).toEqual({ category: 'reimbursement' });
  });
});
