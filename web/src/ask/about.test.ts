import { describe, expect, it } from 'vitest';
import type { Txn } from '../api/types';
import { aboutFor, aboutParam, cleanAbout, parseAboutParam, type AboutIn } from './about';

// A row carrying every kind of free text a transaction can hold.
const TXN: Txn = {
  id: 345, account_id: 3, account_name: 'Alvarez Checking', posted_at: '2026-10-16', amount_cents: -8072,
  raw_description: 'STREAMBOX 4417', merchant: 'StreamBox', category: 'uncategorized', is_business: false,
  is_transfer: false, business_pct: 0, business_line: null, business_source: 'none', category_source: 'none',
  reviewed_at: null, from_bank: true, nickname: 'zorblax', note_count: 2,
};

describe('aboutFor (Ask about this, Privacy tests: Web)', () => {
  it('each surface sends exactly its keys', () => {
    const keys = (a: AboutIn) => Object.keys(a).sort();
    expect(keys(aboutFor.account({ id: 12 }))).toEqual(['id', 'kind']);
    expect(keys(aboutFor.transaction(TXN))).toEqual(['id', 'kind']);
    expect(keys(aboutFor.flag({ id: 7 }))).toEqual(['id', 'kind']);
    expect(keys(aboutFor.category('dining', '2026-10'))).toEqual(['category', 'kind', 'month']);
    expect(keys(aboutFor.plan())).toEqual(['kind']);
    expect(keys(aboutFor.care())).toEqual(['kind']);
    expect(keys(aboutFor.scenario({ id: 3 }))).toEqual(['id', 'kind']);
  });
  it("a transaction's request carries none of its words or values", () => {
    expect(aboutFor.transaction(TXN)).toStrictEqual({ kind: 'transaction', id: 345 });
    const out = JSON.stringify(aboutFor.transaction(TXN));
    for (const w of ['zorblax', 'StreamBox', 'STREAMBOX', '4417', 'Alvarez', '8072', '2026-10-16']) expect(out).not.toContain(w);
  });
  it('cleanAbout keeps only the request’s own keys, whatever a caller added', () => {
    expect(cleanAbout({ kind: 'account', id: 12, label: 'Alvarez Checking' } as unknown as AboutIn)).toStrictEqual({ kind: 'account', id: 12 });
    expect(cleanAbout({ kind: 'care', id: 3, level: 'x' } as unknown as AboutIn)).toStrictEqual({ kind: 'care', id: 3 });
    expect(cleanAbout({ kind: 'care', note: 'zorblax' } as unknown as AboutIn)).toStrictEqual({ kind: 'care' });
    expect(cleanAbout({ kind: 'category', category: 'dining', month: '2026-10', name: 'Sam' } as unknown as AboutIn))
      .toStrictEqual({ kind: 'category', category: 'dining', month: '2026-10' });
  });
});

describe('?about= (P25)', () => {
  it('reads each form and writes it back the same', () => {
    for (const s of ['account:12', 'category:dining:2026-10', 'transaction:345', 'plan', 'flag:7', 'care', 'care:3']) {
      const a = parseAboutParam(s);
      expect(a).not.toBeNull();
      expect(aboutParam(a!)).toBe(s);
    }
  });
  it('ignores anything else', () => {
    for (const s of [null, '', 'account', 'account:', 'account:0', 'account:12:3', 'account:x', 'account:12 ', 'category:dining',
      'category:Eating out:2026-10', 'category:dining:2026-13', 'plan:1', 'nickname:3', 'care:-1']) {
      expect(parseAboutParam(s)).toBeNull();
    }
  });
});
