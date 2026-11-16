import { describe, expect, it } from 'vitest';
import { OCT, SEP, TARGETS, TRENDS, TRENDS6 } from './fixtures';
import { NOV_SECTION, OCT_SECTION } from './setasides/fixtures';
import {
  acceptAll, changeSummary, dayLabel, daysLeftText, draftErrors, draftFrom, fillPct, headFigure, headParts, joinNames, occasionalLine,
  ordinal, overInText, paceText, readDraft, rowChanged, setAsideLine, shiftMonth, steadyLine, todayPct, totals, trendSub, unsortedText,
} from './model';

const row = (c: string) => OCT.everyday.find((r) => r.category === c)!;

describe('the month head', () => {
  it('reads days left, everyday against its targets and fixed costs', () => {
    expect(headParts(OCT)).toEqual(['6 days left', 'Flexible $3,391 of $3,550', 'Fixed costs $4,583']);
  });
  it('a finished month says how far over or under the plan it ended', () => {
    expect(headParts(SEP)).toEqual(['$172 over', 'Flexible $3,722 of $3,550', 'Fixed costs $4,590']);
    expect(headParts({ ...SEP, head: { ...SEP.head, spent_cents: 800_000 } })[0]).toBe('$140 under');
    expect(headParts({ ...SEP, head: { ...SEP.head, spent_cents: 814_000 } })[0]).toBe('On the plan');
  });
  it('heads the month with its figure of the plan when there are everyday targets', () => {
    expect(headFigure(OCT)).toEqual({ amount: '$7,974', tail: 'of $8,140' });
    expect(headFigure(SEP)).toEqual({ amount: '$8,312', tail: 'of $8,140' });
  });
  it('without an everyday target says what was spent, judged against nothing (ruling 26)', () => {
    // The plan would be the fixed costs alone, so everyday spending would read as going over it.
    const now = { ...OCT, head: { ...OCT.head, everyday_target_cents: 0, planned_cents: 459_000 } };
    expect(headFigure(now)).toEqual({ amount: '$7,974', tail: 'spent' });
    expect(headParts(now)).toEqual(['6 days left', 'Flexible $3,391', 'Fixed costs $4,583']);
    const done = { ...SEP, head: { ...SEP.head, everyday_target_cents: 0, planned_cents: 459_000 } };
    expect(headFigure(done)).toEqual({ amount: '$8,312', tail: 'spent' });
    expect(headParts(done)).toEqual(['Flexible $3,722', 'Fixed costs $4,590']);
    const nothing = { ...SEP, head: { ...SEP.head, planned_cents: 0, everyday_target_cents: 0, fixed_expected_cents: 0, fixed_summary: 'none' as const } };
    expect(headFigure(nothing)).toEqual({ amount: '$8,312', tail: 'spent' });
    expect(headParts(nothing)).toEqual(['Flexible $3,722', 'Fixed costs $4,590']);
  });
  it('names fixed costs by their sum when none of them had anything to judge it by (ruling 19)', () => {
    expect(headParts({ ...OCT, head: { ...OCT.head, fixed_summary: 'none' } })[2]).toBe('Fixed costs $4,583');
  });
  it('says the last day and one day, fixed costs still to come, and everyday without targets', () => {
    expect([daysLeftText(0), daysLeftText(1), daysLeftText(6)]).toEqual(['Last day', '1 day left', '6 days left']);
    expect(headParts({ ...OCT, head: { ...OCT.head, fixed_summary: 'to_come', fixed_not_yet: 2 } })[2]).toBe('Fixed costs $4,583 so far, 2 still to come');
    expect(headParts({ ...OCT, head: { ...OCT.head, everyday_target_cents: 0 } })[1]).toBe('Flexible $3,391');
    expect(headParts({ ...OCT, fixed: [], head: { ...OCT.head, fixed_summary: 'none' } })).toHaveLength(2);
  });
  it('says how much more than usual the bills over it came to, from the server (P10)', () => {
    expect(headParts({ ...OCT, head: { ...OCT.head, fixed_summary: 'more', fixed_more_cents: 9_000 } })[2]).toBe('Fixed costs $4,583, $90 more than usual');
  });
  it('names a payment made once in a while under the plan figure, and nothing in a month without one', () => {
    expect(occasionalLine(OCT)).toBeNull();
    const taxes = { ...OCT, occasional: [{ category: 'taxes', kind: 'occasional' as const, spent_cents: 421_000, paid_on: '2026-10-20' }], head: { ...OCT.head, occasional_cents: 421_000 } };
    expect(occasionalLine(taxes)).toBe('and $4,210 in Taxes, paid once in a while');
    const two = { ...taxes, occasional: [...taxes.occasional, { category: 'insurance', kind: 'occasional' as const, spent_cents: 90_000, paid_on: '2026-10-02' }], head: { ...OCT.head, occasional_cents: 511_000 } };
    expect(occasionalLine(two)).toBe('and $5,110 paid once in a while');
  });
});

describe('pace rows', () => {
  it('words each state', () => {
    expect(paceText(row('dining'), true)).toBe('On track');
    expect(paceText(row('shopping'), true)).toBe('Over by $112');
    expect(paceText(row('groceries'), true)).toBe('On track');
    expect(paceText(row('groceries'), false)).toBe('$260 to spare');
    expect(paceText({ ...row('groceries'), spent_cents: 129_600 }, false)).toBe('Within the target');
    expect(paceText(row('personal'), true)).toBe('No target · typically $90 a month');
    expect(paceText({ ...row('personal'), typical_cents: null }, true)).toBe('No target');
    expect(paceText({ ...row('personal'), typical_cents: 0 }, true)).toBe('No target');
    expect([unsortedText(1), unsortedText(7)]).toEqual(['1 transaction without a category', '7 transactions without a category']);
  });
  it('fills to the target, full when over, on a loose scale without one, and marks today only this month', () => {
    expect(fillPct(46_800, 50_000, 0)).toBe(94);
    expect(fillPct(51_200, 40_000, 0)).toBe(100);
    expect([fillPct(1, 0, 0), fillPct(0, 0, 0)]).toEqual([100, 0]);
    expect(fillPct(8_400, null, 104_000)).toBe(8);
    expect(fillPct(8_400, null, 0)).toBe(0);
    expect(todayPct(OCT)).toBe(81);
    expect(todayPct(SEP)).toBeNull();
  });
});

describe('small words', () => {
  it('dates, ordinals, months and lists', () => {
    expect(dayLabel('2026-10-01')).toBe('Oct 1');
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 31].map(ordinal)).toEqual(['1st', '2nd', '3rd', '4th', '11th', '12th', '13th', '21st', '22nd', '23rd', '31st']);
    expect([shiftMonth('2026-01', -1), shiftMonth('2026-12', 1), shiftMonth('2026-10', -1)]).toEqual(['2025-12', '2027-01', '2026-09']);
    expect([joinNames(['Housing']), joinNames(['Housing', 'Giving']), joinNames(['Housing', 'Insurance', 'Giving'])]).toEqual(['Housing', 'Housing and Giving', 'Housing, Insurance and Giving']);
  });
});

describe('Over time', () => {
  const t = (c: string) => TRENDS6.categories.find((r) => r.category === c)!;
  const t12 = (c: string) => TRENDS.categories.find((r) => r.category === c)!;
  it('counts over the months the view shows: 6, or 12', () => {
    expect(overInText(t12('dining'))).toEqual({ text: 'Over in 4 of the last 12 months', strong: true });
    expect(overInText(t12('groceries'))).toEqual({ text: 'Over in 1 of the last 12 months', strong: false });
    expect(overInText({ ...t12('groceries'), over_in: 0 })).toEqual({ text: 'Under target all 12 months', strong: false });
    // A young book in the 12-month view counts the months it has.
    expect(overInText({ ...t12('dining'), over_in: 2, over_of: 4 })).toEqual({ text: 'Over in 2 of the last 4 months', strong: false });
  });
  it('counts the months over the target, strong at 3 or more', () => {
    expect(overInText(t('dining'))).toEqual({ text: 'Over in 3 of the last 6 months', strong: true });
    expect(overInText({ ...t('dining'), over_in: 1 })).toEqual({ text: 'Over in 1 of the last 6 months', strong: false });
    expect(overInText(t('groceries'))).toEqual({ text: 'Under target all 6 months', strong: false });
    expect(overInText({ ...t('groceries'), over_of: 4 })).toEqual({ text: 'Under target all 4 months', strong: false });
    // A book with one finished month behind it: no "1 of the last 1 months".
    expect(overInText({ ...t('dining'), over_in: 1, over_of: 1 })).toEqual({ text: 'Over last month', strong: false });
    expect(overInText({ ...t('groceries'), over_of: 1 })).toEqual({ text: 'Under target last month', strong: false });
    expect(overInText(t('personal'))).toEqual({ text: 'No target', strong: false });
    expect(overInText(t('utilities'))).toEqual({ text: 'Expected $410', strong: false });
    expect(trendSub(t('dining'))).toBe('Target $500 · typical month $470');
    expect(trendSub(t('personal'))).toBe('Typical month $90');
    expect(steadyLine(TRENDS.categories)).toBe('Housing, Insurance and Giving are the same every month, so they are not drawn.');
  });
});

describe('Set targets', () => {
  it('starts from what is saved and finds only what changed', () => {
    const d = draftFrom(TARGETS);
    expect(d.rows.groceries).toEqual({ kind: 'everyday', text: '1,300' });
    expect(d.rows.personal).toEqual({ kind: 'everyday', text: '' });
    const r = readDraft(TARGETS, d);
    expect('body' in r && r.body).toEqual({ targets: [] });
    const next = { ...d, rows: { ...d.rows, groceries: { kind: 'everyday' as const, text: '1,250' }, subscriptions: { kind: 'everyday' as const, text: '' } } };
    const p = readDraft(TARGETS, next);
    if (!('body' in p)) throw new Error(p.error);
    expect(p.body.targets).toEqual([{ category: 'groceries', kind: 'everyday', monthly_cents: 125_000 }, { category: 'subscriptions', kind: 'everyday', monthly_cents: null }]);
    expect(changeSummary(TARGETS, p)).toBe('Groceries $1,300 → $1,250 · Subscriptions bill → flexible');
  });
  it('refuses what it cannot read, naming the row, and ignores an amount on a once-in-a-while row', () => {
    const d = draftFrom(TARGETS);
    expect(readDraft(TARGETS, { ...d, rows: { ...d.rows, dining: { kind: 'everyday', text: '12.345' } } })).toEqual({ error: 'Use at most two decimals.', category: 'dining' });
    expect(readDraft(TARGETS, { ...d, rows: { ...d.rows, taxes: { kind: 'occasional', text: '99' } } })).toEqual({ body: { targets: [] }, changed: [] });
  });
  it("words a kind-only change as the server's event line does, and an amount with its cents", () => {
    // Ruling 4: no colon, the kinds lower-case, no "the typical month → no target" (tests/test_spending_targets.py).
    const d = draftFrom(TARGETS);
    const kindOnly = readDraft(TARGETS, { ...d, rows: { ...d.rows, subscriptions: { kind: 'everyday', text: '' }, taxes: { kind: 'fixed', text: '' } } });
    if (!('body' in kindOnly)) throw new Error(kindOnly.error);
    expect(changeSummary(TARGETS, kindOnly)).toBe('Subscriptions bill → flexible · Taxes once in a while → bill');
    const both = readDraft(TARGETS, { ...d, rows: { ...d.rows, subscriptions: { kind: 'everyday', text: '120' } } });
    if (!('body' in both)) throw new Error(both.error);
    expect(changeSummary(TARGETS, both)).toBe('Subscriptions bill → flexible, the typical month → $120');
    // A figure with cents keeps them, as the event line does, so two amounts a few cents apart still read as a change.
    const cents = readDraft(TARGETS, { ...d, rows: { ...d.rows, dining: { kind: 'everyday', text: '500.25' }, personal: { kind: 'everyday', text: '470.50' } } });
    if (!('body' in cents)) throw new Error(cents.error);
    expect(changeSummary(TARGETS, cents)).toBe('Eating out $500 → $500.25 · Personal no target → $470.50');
  });
  it('sends no amount for a row switched to once in a while, whatever its field held (an amount there is refused)', () => {
    const d = draftFrom(TARGETS);
    const p = readDraft(TARGETS, { ...d, rows: { ...d.rows, groceries: { kind: 'occasional', text: '1,300' } } });
    if (!('body' in p)) throw new Error(p.error);
    expect(p.body.targets).toEqual([{ category: 'groceries', kind: 'occasional', monthly_cents: null }]);
    expect(changeSummary(TARGETS, p)).toBe('Groceries flexible → once in a while, $1,300 → no target');
  });
  it('accepts every everyday suggestion and adds up a month', () => {
    const all = acceptAll(TARGETS, draftFrom(TARGETS));
    expect([all.rows.groceries.text, all.rows.travel.text, all.rows.housing.text]).toEqual(['1,240', '', '']);
    expect(totals(TARGETS, draftFrom(TARGETS))).toEqual({ everyday: 355_000, fixed: 459_000, month: 814_000, income: 1_020_000, leaves: 206_000 });
  });
  it("checks every amount against the server's bounds, so its 422 is only a backstop (ruling 25)", () => {
    const d = draftFrom(TARGETS);
    const rows = (over: Record<string, string>) => ({ ...d.rows, ...Object.fromEntries(Object.entries(over).map(([c, text]) => [c, { ...d.rows[c], text }])) });
    // A target from $0 to $1,000,000.
    expect(readDraft(TARGETS, { ...d, rows: rows({ dining: '1,000,000.01' }) })).toEqual({ error: 'Enter a target from $0 to $1,000,000, or leave it blank.', category: 'dining' });
    expect(readDraft(TARGETS, { ...d, rows: rows({ housing: '-5' }) })).toEqual({ error: 'Enter a target from $0 to $1,000,000, or leave it blank.', category: 'housing' });
    const top = readDraft(TARGETS, { ...d, rows: rows({ dining: '1,000,000' }) });
    expect('body' in top && top.body.targets).toEqual([{ category: 'dining', kind: 'everyday', monthly_cents: 100_000_000 }]);
  });
  it('adds up an amount it cannot read, or one out of range, as what is saved (fix round 1, M1)', () => {
    const d = draftFrom(TARGETS);
    const base = totals(TARGETS, d);
    for (const text of ['12.345', '2,000,000']) {
      // Groceries is saved at $1,300; Housing has no amount, so the typical $2,680 stands; Personal has none at all.
      const bad = { ...d, rows: { ...d.rows, groceries: { kind: 'everyday' as const, text }, housing: { kind: 'fixed' as const, text }, personal: { kind: 'everyday' as const, text } } };
      expect(totals(TARGETS, bad)).toEqual(base);
    }
  });
  it('names every field it cannot read, not only the first', () => {
    const d = draftFrom(TARGETS);
    expect(draftErrors(TARGETS, d)).toEqual({});
    const bad = { ...d, rows: { ...d.rows, dining: { kind: 'everyday' as const, text: '12.345' }, housing: { kind: 'fixed' as const, text: '2,000,000' },
      taxes: { kind: 'occasional' as const, text: '99.999' } } };
    expect(draftErrors(TARGETS, bad)).toEqual({
      dining: 'Use at most two decimals.', housing: 'Enter a target from $0 to $1,000,000, or leave it blank.', });
  });
  it('a row is changed when its kind or the amount it reads as differs, not its text (an explicit $0 is a change, ruling 21)', () => {
    const groceries = TARGETS.categories[0];
    const personal = TARGETS.categories.find((r) => r.category === 'personal')!;
    expect(rowChanged(groceries, { kind: 'everyday', text: '1,300' })).toBe(false);
    expect(rowChanged(groceries, { kind: 'everyday', text: '1,300.00' })).toBe(false);
    expect(rowChanged(groceries, { kind: 'everyday', text: '1,250' })).toBe(true);
    expect(rowChanged(groceries, { kind: 'everyday', text: '' })).toBe(true);
    expect(rowChanged(groceries, { kind: 'everyday', text: '12.345' })).toBe(true);
    expect(rowChanged(groceries, { kind: 'fixed', text: '1,300' })).toBe(true);
    expect(rowChanged(personal, { kind: 'everyday', text: '' })).toBe(false);
    expect(rowChanged(personal, { kind: 'everyday', text: '0' })).toBe(true);
    const p = readDraft(TARGETS, { ...draftFrom(TARGETS), rows: { ...draftFrom(TARGETS).rows, personal: { kind: 'everyday', text: '0' }, groceries: { kind: 'everyday', text: '' } } });
    expect('body' in p && p.body.targets).toEqual([
      { category: 'groceries', kind: 'everyday', monthly_cents: null }, { category: 'personal', kind: 'everyday', monthly_cents: 0 }]);
  });
});

describe('the head with set-asides (11c)', () => {
  it('adds the set-aside part and names a matched payment under the figure', () => {
    const oct = { ...OCT, set_aside: OCT_SECTION, head: { ...OCT.head, set_aside_cents: 154_400, spent_cents: 951_800, planned_cents: 968_400 } };
    expect(headParts(oct)).toEqual(['6 days left', 'Flexible $3,391 of $3,550', 'Fixed costs $4,583', 'Set aside $1,544']);
    expect(setAsideLine(oct)).toBeNull();
    const nov = { ...oct, set_aside: NOV_SECTION, head: { ...oct.head, paid_from_set_aside_cents: 421_000 } };
    expect(setAsideLine(nov)).toBe('and $4,210 property tax, paid from Setting aside');
    expect(headParts({ ...OCT, set_aside: null })).toEqual(headParts(OCT));
    expect(headParts({ ...OCT, set_aside: null })).toHaveLength(3);
    expect(headParts({ ...oct, set_aside: { ...OCT_SECTION, monthly_cents: 0, count: 0 } })).toHaveLength(3);
  });
});
