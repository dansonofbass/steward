import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Txn } from '../../api/types';
import { callsTo, reply, stubFetch, wrapBook } from '../../test-utils';
import { type ActionHooks, useReviewActions } from './useReviewActions';

const TXN: Txn = {
  id: 7, account_id: 1, account_name: 'Checking', posted_at: '2026-10-10', amount_cents: -1200, raw_description: 'UNION SERVICE CENTER',
  merchant: null, category: 'uncategorized', is_business: false, is_transfer: false, business_pct: 0, business_line: null,
  business_source: 'none', category_source: 'none', reviewed_at: null, from_bank: true, matching: 2, reimburse_ok: false,
};

function Harness({ txn = TXN, hooks }: { txn?: Txn; hooks: ActionHooks }) {
  const a = useReviewActions(txn, hooks);
  return (
    <div>
      <button type="button" onClick={() => { a.sort('transport'); }}>sort</button>
      <button type="button" onClick={() => { a.sort('reimbursement'); }}>repaid</button>
      <button type="button" onClick={() => { a.post('snooze'); }}>snooze</button>
      <button type="button" onClick={a.toggleBusiness}>business</button>
      <button type="button" onClick={() => { a.setAlso(false); }}>untick</button>
      <span data-testid="state">{`${a.busy}|${a.error ?? ''}|${a.chosen ?? ''}`}</span>
    </div>
  );
}

describe("a card's requests (review focus, Build 3)", () => {
  it('a sort says it is starting, sends the box and Business, and hands back the reply with the rows it spread to', async () => {
    const hooks = { onStart: vi.fn(), onDone: vi.fn(), onFail: vi.fn() };
    const fetchMock = stubFetch({ 'PATCH /api/transactions/7': { ...TXN, category: 'transport', result: { category: 'transport', applied: 2, ids: [40, 41], rule: 'made', undo: 'tok' } } });
    wrapBook(<Harness hooks={hooks} />);
    fireEvent.click(screen.getByRole('button', { name: 'business' }));
    fireEvent.click(screen.getByRole('button', { name: 'sort' }));
    expect(hooks.onStart).toHaveBeenCalledWith('sort', 'transport');
    expect(screen.getByTestId('state')).toHaveTextContent('true||transport');
    await waitFor(() => expect(hooks.onDone).toHaveBeenCalledTimes(1));
    expect(hooks.onDone.mock.calls[0][0]).toMatchObject({ kind: 'sort', category: 'transport', applied: 2, ids: [40, 41] });
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/7')[0].body).toEqual({ category: 'transport', is_business: true, apply_to_matching: true });
  });

  it('unticked, the box goes as false; a refusal says why and clears the choice', async () => {
    const hooks = { onDone: vi.fn(), onFail: vi.fn() };
    const fetchMock = stubFetch({ 'PATCH /api/transactions/7': () => reply({ error: 'That isn’t one of the categories.' }, 422) });
    wrapBook(<Harness hooks={hooks} />);
    fireEvent.click(screen.getByRole('button', { name: 'untick' }));
    fireEvent.click(screen.getByRole('button', { name: 'sort' }));
    await waitFor(() => expect(hooks.onFail).toHaveBeenCalledWith('That isn’t one of the categories.'));
    expect(screen.getByTestId('state')).toHaveTextContent('false|That isn’t one of the categories.|');
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/7')[0].body).toEqual({ category: 'transport', apply_to_matching: false });
    expect(hooks.onDone).not.toHaveBeenCalled();
  });

  it('Snooze posts and hands back until; a repayment with nobody to pay asks first and sends nothing', async () => {
    const hooks = { onStart: vi.fn(), onDone: vi.fn() };
    const fetchMock = stubFetch({ 'POST /api/review/7/snooze': { undo: 'tok-s', until: '2026-11-06' }, '/api/reimburse/payers': { payers: [] } });
    wrapBook(<Harness hooks={hooks} />);
    fireEvent.click(screen.getByRole('button', { name: 'repaid' }));
    expect(callsTo(fetchMock, 'PATCH', '/api/transactions/7')).toHaveLength(0);
    expect(hooks.onStart).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'snooze' }));
    await waitFor(() => expect(hooks.onDone).toHaveBeenCalledWith({ kind: 'snooze', reply: { undo: 'tok-s', until: '2026-11-06' } }));
    expect(hooks.onStart).toHaveBeenCalledWith('snooze', null);
  });
});
