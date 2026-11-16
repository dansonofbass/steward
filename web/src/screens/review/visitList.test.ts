import { describe, expect, it } from 'vitest';
import type { Txn } from '../../api/types';
import { undoOf, type Visit, visitReducer } from './visitList';

const t = (id: number, extra: Partial<Txn> = {}): Txn => ({
  id, account_id: 1, account_name: 'Checking', posted_at: '2026-10-10', amount_cents: -1200, raw_description: `SHOP ${id}`,
  merchant: null, category: 'uncategorized', is_business: false, is_transfer: false, business_pct: 0, business_line: null,
  business_source: 'none', category_source: 'none', reviewed_at: null, from_bank: true, ...extra,
});
const ids = (v: Visit) => v.map((r) => `${r.id}:${r.outcome.kind}`);

describe("the list's visit (review focus P20, P21)", () => {
  it('starts from the queue, marks a sort and its matched rows, and never reorders', () => {
    let v = visitReducer([], { type: 'sync', queue: [t(1), t(2), t(3), t(4)] });
    v = visitReducer(v, { type: 'acted', id: 2, outcome: { kind: 'sorted', category: 'gifts', n: 1, entry: 'e1' }, matched: { ids: [4, 99], category: 'gifts' } });
    expect(ids(v)).toEqual(['1:waiting', '2:sorted', '3:waiting', '4:matched']);
    expect(v[3].outcome).toEqual({ kind: 'matched', category: 'gifts', entry: 'e1' });
    expect(undoOf(v[1].outcome)).toBe('e1');
    expect(undoOf(v[3].outcome)).toBeNull();
  });

  it('a refetch updates waiting rows, marks missing ones elsewhere, keeps outcomes and appends new rows at the end', () => {
    let v = visitReducer([], { type: 'sync', queue: [t(1), t(2), t(3)] });
    v = visitReducer(v, { type: 'acted', id: 1, outcome: { kind: 'snoozed', until: '2026-11-06', entry: 'e1' } });
    v = visitReducer(v, { type: 'sync', queue: [t(2, { nickname: 'Gym' }), t(5)] });
    expect(ids(v)).toEqual(['1:snoozed', '2:waiting', '3:elsewhere', '5:waiting']);
    expect(v[1].txn.nickname).toBe('Gym');
    v = visitReducer(v, { type: 'sync', queue: [t(0), t(2), t(3), t(5)] });       // an older row: still at the end
    expect(ids(v)).toEqual(['1:snoozed', '2:waiting', '3:waiting', '5:waiting', '0:waiting']);
  });

  it("Undo restores every row of its entry, the parent's matches included, and counts the return", () => {
    let v = visitReducer([], { type: 'sync', queue: [t(1), t(2), t(3)] });
    v = visitReducer(v, { type: 'acted', id: 1, outcome: { kind: 'sorted', category: 'gifts', n: 1, entry: 'e1' }, matched: { ids: [3], category: 'gifts' } });
    v = visitReducer(v, { type: 'bulk', ids: [2], category: 'travel', entry: 'e2' });
    v = visitReducer(v, { type: 'restore', entry: 'e1' });
    expect(ids(v)).toEqual(['1:waiting', '2:bulk', '3:waiting']);
    expect([v[0].back, v[1].back, v[2].back]).toEqual([1, 0, 1]);
    expect(visitReducer(v, { type: 'clear' })).toEqual([]);
  });

  it('an Undo of an action made in the other view brings its card back at the end', () => {
    const v = visitReducer([], { type: 'sync', queue: [t(2), t(3)] });
    expect(ids(visitReducer(v, { type: 'restore', entry: 'e9', card: t(1) }))).toEqual(['2:waiting', '3:waiting', '1:waiting']);
    expect(ids(visitReducer(v, { type: 'restore', entry: 'e9', card: t(2) }))).toEqual(['2:waiting', '3:waiting']);   // never twice
  });
});
