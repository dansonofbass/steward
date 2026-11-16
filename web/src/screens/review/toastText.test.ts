import { describe, expect, it } from 'vitest';
import type { Txn, TxnPatchReply } from '../../api/types';
import { TEST_NOW } from '../../test-clock';
import { displayName, ignoreToast, likeLine, slimText, snoozeToast, sortToast, type ToastBody } from './toastText';
import type { SortDone } from './useReviewActions';

const TXN: Txn = {
  id: 1, account_id: 1, account_name: 'Rewards Card', posted_at: '2026-10-16', amount_cents: -8072, raw_description: 'GREENLEAF MARKET',
  merchant: null, category: 'uncategorized', is_business: false, is_transfer: false, business_pct: 0, business_line: null,
  business_source: 'none', category_source: 'none', reviewed_at: null, from_bank: true,
};
const plain = (b: { parts: { text: string }[] }) => b.parts.map((p) => p.text).join('');
const done = (category: string, applied: number, reimburse: object | null = null): SortDone => ({
  kind: 'sort', category, applied, ids: [],
  reply: { ...TXN, category, result: { category, applied, rule: 'made', undo: 't', reimburse } } as TxnPatchReply,
});

describe('the toast and slim-row text (review focus, Copy)', () => {
  it('names the row by its nickname, then merchant, then the bank text', () => {
    expect(displayName(TXN)).toBe('GREENLEAF MARKET');
    expect(displayName({ ...TXN, merchant: 'PayPal' })).toBe('PayPal');
    expect(displayName({ ...TXN, merchant: 'PayPal', nickname: 'Disney+' })).toBe('Disney+');
    expect([likeLine(1), likeLine(6)]).toEqual(['Also the one like it', 'Also the 6 like it']);
  });

  it('a sort: SORTED · name → category, with the count of the rows like it', () => {
    const one: ToastBody = sortToast(TXN, done('groceries', 0));
    expect(one.tag).toBe('SORTED');
    expect(plain(one)).toBe('GREENLEAF MARKET → Groceries');
    expect(plain(sortToast(TXN, done('groceries', 6)))).toBe('GREENLEAF MARKET + 6 like it → Groceries');
  });

  it("a reimbursement adds today's facts, and Settle when offered; all square is the toast's text", () => {
    const marked = sortToast({ ...TXN, raw_description: 'HILTON CHICAGO IL', amount_cents: -41218 },
      done('travel', 0, { change: 'marked', reimburser_id: 1, payer: 'Acme', was_cents: 82817, owed_cents: 124035 }));
    expect(plain(marked)).toBe('HILTON CHICAGO IL → Travel Travel, reimbursable. Acme owes you $412.18 more ($1,240.35 in all).');
    expect(marked.settle).toBeNull();
    const repaid = sortToast({ ...TXN, amount_cents: 33965 },
      done('reimbursement', 0, { change: 'repaid', reimburser_id: 1, payer: 'Acme', was_cents: 40000, owed_cents: 6035 }));
    expect(plain(repaid)).toBe('GREENLEAF MARKET → Reimbursement Reimbursement from Acme. Acme now owes you $60.35.');
    expect(repaid.settle).toEqual({ id: 1, cents: 6035 });
    const square = sortToast({ ...TXN, amount_cents: 33965 },
      done('reimbursement', 0, { change: 'repaid', reimburser_id: 1, payer: 'Acme', was_cents: 33965, owed_cents: 0 }));
    expect([square.tag, plain(square), square.settle]).toEqual([null, 'All square with Acme.', null]);
  });

  it('Snooze and Ignore are plain sentences', () => {
    expect(plain(snoozeToast('2026-11-06', TEST_NOW))).toBe('Snoozed · back Nov 6');
    expect(plain(ignoreToast(TXN))).toBe('Ignored · GREENLEAF MARKET');
  });

  it('each slim row says what happened, after its stamp tag', () => {
    const row = (outcome: object) => slimText({ id: 1, txn: TXN, outcome, back: 0 } as never, TEST_NOW);
    const said = (outcome: object) => { const s = row(outcome); return `${s.tag} · ${plain(s)}`; };
    expect(said({ kind: 'sorted', category: 'groceries', n: 0, entry: 'e1' })).toBe('SORTED · GREENLEAF MARKET as Groceries');
    expect(said({ kind: 'sorted', category: 'groceries', n: 6, entry: 'e1' })).toBe('SORTED · GREENLEAF MARKET + 6 like it as Groceries');
    expect(said({ kind: 'matched', category: 'groceries', entry: 'e1' })).toBe('SORTED · GREENLEAF MARKET as Groceries');
    expect(said({ kind: 'bulk', category: 'gifts', entry: 'e2' })).toBe('SORTED · GREENLEAF MARKET as Gifts');
    expect(said({ kind: 'snoozed', until: '2026-11-06', entry: 'e3' })).toBe('SNOOZED · GREENLEAF MARKET · back Nov 6');
    expect(said({ kind: 'ignored', entry: 'e4' })).toBe('IGNORED · GREENLEAF MARKET');
    expect(said({ kind: 'elsewhere' })).toBe('SORTED · GREENLEAF MARKET');
  });
});
