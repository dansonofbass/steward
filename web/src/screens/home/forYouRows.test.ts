import { describe, expect, it } from 'vitest';
import type { HomeData } from '../../api/home';
import type { ReviewQueue } from '../../api/types';
import { profileState } from '../profile/fixtures';
import { HOME, homeWith } from './fixtures';
import { forYouRows } from './forYouRows';

const DINING = { category: 'dining', spent_cents: 64_000, target_cents: 50_000, over_cents: 14_000, over_level: 'clear' as const };
const SHOPPING = { category: 'shopping', spent_cents: 51_200, target_cents: 40_000, over_cents: 11_200, over_level: 'clear' as const };
const REVIEW = (count: number, business = 0) => ({ uncategorized: [], count, duplicates: [], duplicate_count: 0, top_categories: [], business: [], business_count: business, background: { pending: 0, done: 0, waiting: false } }) as unknown as ReviewQueue;
const TAX = { notice: { due: '2027-01-15', line: 'Quarterly taxes: $2,400 due Jan 15', federal_cents: 180_000, state_cents: 60_000 } };
const ALL: HomeData = homeWith({
  for_you: [
    { kind: 'event', id: 41, event_kind: 'sync', level: 'warn', message: 'Big Bank needs you to sign in again at SimpleFIN' },
    { kind: 'event', id: 42, event_kind: 'chat', level: 'error', message: 'A sent answer is missing from the record.' },
    { kind: 'event', id: 43, event_kind: 'mail', level: 'info', message: "An email to Sam couldn't be sent." },
    { kind: 'same_account', n: 1, name: "Nora's 529" },
    { kind: 'untyped', n: 1 },
    { kind: 'owed', payers: [{ name: 'Northwind', cents: 118_400 }], others: { n: 0, cents: 0 } },
  ],
  signs: { ...HOME.signs, flexible: { spent_cents: 314_000, target_cents: 420_000, rows: [DINING] } },
});
const every = { data: ALL, canEdit: true, review: REVIEW(12), tax: TAX, profile: profileState({ you: { status: 'done' } }) };

describe('forYouRows (Home spec, For you)', () => {
  it("holds every kind in P18's order, each with its words and its link", () => {
    expect(forYouRows(every).map((r) => [r.text, r.action?.label, r.action?.to, r.amber])).toEqual([
      ['Big Bank needs you to sign in again at SimpleFIN', 'Fix ›', '/settings/banks', true],
      ['A sent answer is missing from the record.', 'See ›', '/settings/chat/sent', true],
      ["An email to Sam couldn't be sent.", 'See ›', '/settings/log', false],
      ['Eating out is $140 over its target', 'See ›', '/spending/dining?month=2026-10', true],
      ["Same account? Nora's 529 came in twice", 'Answer ›', '/accounts', false],
      ['1 new account needs a type', 'Set ›', '/settings/banks', false],
      ['12 to sort in Review', 'Review ›', '/review', false],
      ['Northwind owes you $1,184', 'See ›', '/spending/reimbursements', false],
      ['Quarterly taxes: $2,400 due Jan 15', 'See ›', '/taxes', false],
      ['Your profile is 1 of 5 done. Next: Kids and college, about 2 minutes', 'Continue ›', '/profile/kids/kids', false],
    ]);
    const rows = forYouRows(every);
    expect(rows.slice(0, 3).map((r) => r.dismiss)).toEqual([41, 42, 43]);
    expect(rows[9].later).toBe(true);
  });

  it('a viewer reads the event messages with no action, and never the Review row', () => {
    const rows = forYouRows({ ...every, canEdit: false });
    expect(rows.slice(0, 3).map((r) => [r.action, r.dismiss])).toEqual([[undefined, undefined], [undefined, undefined], [undefined, undefined]]);
    expect(rows.map((r) => r.key)).not.toContain('review');
  });

  it('over target: one category opens it, more open the Flexible section; a little over is not amber', () => {
    const two = forYouRows({ data: homeWith({ signs: { ...HOME.signs, flexible: { spent_cents: 0, target_cents: 420_000, rows: [DINING, SHOPPING] } } }), canEdit: true });
    expect(two).toEqual([{ key: 'over', text: '2 categories are over: Eating out $140 · Shopping $112', amber: true, action: { label: 'See ›', to: '/spending?month=2026-10#flexible' } }]);
    const little = forYouRows({ data: homeWith({ signs: { ...HOME.signs, flexible: { spent_cents: 0, target_cents: 420_000, rows: [{ ...DINING, spent_cents: 52_000, over_cents: 2_000, over_level: 'little' }] } } }), canEdit: true });
    expect(little.map((r) => [r.text, r.amber])).toEqual([['Eating out is a little over its target · $520 of $500', false]]);
    expect(forYouRows({ data: HOME, canEdit: true })).toEqual([]);              // nothing over: no row (the headline says so)
  });

  it('counts and others read right', () => {
    const data = homeWith({ for_you: [
      { kind: 'same_account', n: 2, name: null }, { kind: 'untyped', n: 3 },
      { kind: 'owed', payers: [{ name: 'Ada', cents: 30_000 }, { name: 'Bo', cents: 20_000 }], others: { n: 1, cents: 10_000 } },
    ] });
    expect(forYouRows({ data, canEdit: true, review: REVIEW(0, 1) }).map((r) => r.text)).toEqual([
      '2 same-account questions', '3 new accounts need a type', '1 to sort in Review', 'Ada owes you $300', 'Bo owes you $200', '1 other owes you $100']);
    const many = homeWith({ for_you: [{ kind: 'owed', payers: [{ name: 'Ada', cents: 30_000 }], others: { n: 3, cents: 30_000 } }] });
    expect(forYouRows({ data: many, canEdit: true }).map((r) => r.text)).toEqual(['Ada owes you $300', '3 others owe you $300']);
  });

  it('no Profile row once it is finished or inside the Later week, and no tax row without a notice', () => {
    const later = profileState({ you: { status: 'done' } }, { later_until: '2099-01-01T00:00:00+00:00' });
    expect(forYouRows({ data: HOME, canEdit: true, profile: later, tax: { notice: null } })).toEqual([]);
  });
});
