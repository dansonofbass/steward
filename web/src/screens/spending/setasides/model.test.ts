import { describe, expect, it } from 'vitest';
import { CAMPS, CARREG, HEATER, HEATER_DETAIL, HEATER_PAID, HOLIDAYS, LIST, NOV_SECTION, OCT_SECTION, PROPTAX, PROPTAX_DETAIL, SUGGESTIONS } from './fixtures';
import type { Draft } from './model';
import { changedBody, checkNotes, costText, dateText, draftFrom, dueSub, dueWhen, emptyDraft, estimateWords, findHref, fundLines, headLine, headParts, headState, lowerFirst, monthWord, nextDueText, notPaidFund, paidLine, paymentMeta, previewLines, previewRequest, readDraft, replaceText, setAsideHeadPart, sourceNotes, stateLine, stateText, stateTone, suggestionWhen, summaryRow, whenWords } from './model';

const AS_OF = '2026-10-25';

describe('the list row', () => {
  it('words the cost and the next due date for each kind', () => {
    expect(costText(PROPTAX)).toBe('$4,210 twice a year');
    expect(costText(HOLIDAYS)).toBe('$1,500 a year');
    expect(costText(HEATER)).toBe('$2,200 once');
    expect(nextDueText(PROPTAX)).toBe('Nov 1, 2026');
    expect(nextDueText(HOLIDAYS)).toBe('Dec 2026');                 // due on the 1st reads as the month
    expect(nextDueText(HEATER)).toBe('About 2028');
    expect(dueWhen(PROPTAX, AS_OF)).toBe('next Nov 1, 2026, in 7 days');
    expect(dueWhen(HOLIDAYS, AS_OF)).toBe('next Dec 2026, in 5 weeks');
    expect(dueWhen(CARREG, AS_OF)).toBe('next Mar 2027, in 5 months');
    expect(dueWhen(HEATER, AS_OF)).toBe('About 2028, 26 months away');
    expect(dueWhen({ ...HEATER, next_due: null, days_until: null, paid: { transaction_id: 404, posted_at: '2026-10-14', cents: 215_000, account_name: 'House fund' } }, AS_OF)).toBe('Paid');
  });
  it('words an unpaid one-off more than six weeks overdue by its due month, never as paid', () => {
    // The server sends next_due null for it too: Paid is keyed on the matched payment, not on next_due.
    const overdue = { ...HEATER, due_year: 2026, due_month: 8, next_due: null, days_until: null, state: 'not_paid' as const, missed_due: '2026-08-01' };
    expect(dueWhen(overdue, AS_OF)).toBe('Due Aug 2026');
    expect(dueWhen({ ...overdue, due_year: 2025, due_month: 12, missed_due: null, state: 'on_track' }, AS_OF)).toBe('Due Dec 2025');
  });
  it('says when in days, weeks or months, before and after (days up to 30 read as days)', () => {
    expect([whenWords(0), whenWords(1), whenWords(6), whenWords(13), whenWords(14), whenWords(30), whenWords(31), whenWords(37), whenWords(59)]).toEqual(
      ['today', 'tomorrow', 'in 6 days', 'in 13 days', 'in 14 days', 'in 30 days', 'in 4 weeks', 'in 5 weeks', 'in 8 weeks']);
    expect([whenWords(-1), whenWords(-5), whenWords(-19), whenWords(-30), whenWords(-43)]).toEqual(['1 day ago', '5 days ago', '19 days ago', '30 days ago', '6 weeks ago']);
    expect(whenWords(60, '2026-12-24', AS_OF)).toBe('in 2 months');
  });
  it('counts calendar months across a December, and words a one-off due next month or overdue', () => {
    expect(whenWords(60, '2027-02-23', '2026-12-24')).toBe('in 2 months');
    expect(whenWords(91, '2027-01-01', '2026-10-01')).toBe('in 3 months');
    expect(dueWhen({ ...HEATER, due_year: 2027, next_due: '2027-01-01', days_until: 8 }, '2026-12-24')).toBe('About 2027, 1 month away');
    expect(dueWhen({ ...HEATER, due_year: 2026, next_due: '2026-10-01', days_until: -24 }, AS_OF)).toBe('About 2026, 24 days ago');
    expect(dateText('2027-01-01', true)).toBe('Jan 2027');
    expect(dateText('2026-12-12')).toBe('Dec 12, 2026');
    expect(monthWord(12)).toBe('December');
    expect(monthWord(1)).toBe('January');
  });
  it('words each state, in the list words, with the account after it', () => {
    expect(stateText(PROPTAX)).toBe('Due in 7 days · $110 short');
    expect(stateText(CAMPS)).toBe('Behind by $200 · $600 put away, $800 should be by now');
    expect(stateText(HEATER)).toBe('On track · nothing due yet');
    expect(stateText({ ...HEATER, should_cents: 8_500, put_away_cents: 8_500 })).toBe('On track');
    expect(stateText(HOLIDAYS)).toBe('No account linked');
    expect(stateText({ ...PROPTAX, state: 'not_paid', missed_due: '2026-11-01', next_due: '2027-04-10' })).toBe('Nov 1 not paid yet');
    expect(stateText({ ...PROPTAX, next_due: '2026-10-20', days_until: -5 })).toBe('Due 5 days ago · $110 short');
    expect(stateLine(PROPTAX)).toBe('Due in 7 days · $110 short · House fund');
    expect(stateLine({ ...PROPTAX, account: { ...PROPTAX.account!, stale: true, as_of: '2026-10-12' } })).toBe('Due in 7 days · $110 short · House fund, balance from Oct 12');
    expect(stateLine({ ...PROPTAX, account: { ...PROPTAX.account!, stale: false, as_of: '2026-10-12' } })).toBe('Due in 7 days · $110 short · House fund');
    expect(stateLine(HOLIDAYS)).toBe('No account linked');
    expect([stateTone('short'), stateTone('behind'), stateTone('not_paid'), stateTone('on_track'), stateTone('no_account')]).toEqual(['soon', 'behind', 'soon', 'track', 'none']);
  });
  it('says which of an estimate the server has not checked', () => {
    expect(checkNotes({ to_check: true, cost_to_check: true })).toEqual(['lifespan to be checked', 'cost to be checked']);
    expect(checkNotes(HEATER.estimate!)).toEqual(['cost to be checked']);
    expect(checkNotes({ to_check: false, cost_to_check: false })).toEqual([]);
    expect(HEATER_DETAIL.estimate?.cost_to_check).toBe(true);
  });
});

describe('the head and the suggestions', () => {
  it('reads the counts and totals', () => {
    expect(headParts(LIST)).toEqual(['7 costs', '$14,592 a year in yearly costs', '$20,200 in big one-offs', '2 need a look']);
    expect(headParts({ ...LIST, count: 1, needs_look: 1, one_off_cents: 0 })).toEqual(['1 cost', '$14,592 a year in yearly costs', '1 needs a look']);
    expect(headParts({ ...LIST, needs_look: 0, yearly_cents: 0 })).toEqual(['7 costs', '$20,200 in big one-offs']);
  });
  it('words a suggestion, a twice-yearly one with its dates in calendar order', () => {
    expect(suggestionWhen(SUGGESTIONS[0])).toBe('Jul · $1,800 a year');
    expect(suggestionWhen(SUGGESTIONS[2])).toBe('Jan, Jul · $900 a year');                 // twice a year, in calendar order
    expect(suggestionWhen({ ...SUGGESTIONS[2], months: [6, 12], yearly_cents: 421_000 })).toBe('Jun, Dec · $4,210 a year');
  });
});

describe("Spending's words", () => {
  it('adds the set-aside part to the head, names a matched payment, and sums the summary row', () => {
    expect(setAsideHeadPart(OCT_SECTION)).toBe('Set aside $1,544');
    expect(paidLine(OCT_SECTION)).toBeNull();
    expect(paidLine(NOV_SECTION)).toBe('and $4,210 property tax, paid from Setting aside');
    expect(paidLine({ ...NOV_SECTION, paid: [...NOV_SECTION.paid, { ...NOV_SECTION.paid[0], name: 'HOA dues', cents: 45_000 }] })).toBe('and $4,660 paid from Setting aside');
    expect(lowerFirst('Property tax')).toBe('property tax');
    expect(lowerFirst('HOA dues')).toBe('HOA dues');
    expect(summaryRow(OCT_SECTION)).toEqual({ name: '7 costs, set aside this month', sub: 'Property tax, Holidays, Car registration and 4 more · $14,592 a year, $20,200 in one-offs' });
    expect(summaryRow(NOV_SECTION)).toEqual({ name: '7 costs, set aside this month', sub: 'Property tax paid Nov 1 · next: Holidays, December' });
    expect(summaryRow({ ...OCT_SECTION, count: 2, names: ['Property tax', 'Holidays'], one_off_cents: 0 })).toEqual({ name: '2 costs, set aside this month', sub: 'Property tax and Holidays · $14,592 a year' });
  });
  it('a December payment names the next month in the new year', () => {
    const dec = { ...NOV_SECTION, paid: [{ ...NOV_SECTION.paid[0], posted_at: '2026-12-01' }], next: { name: 'Car registration', next_due: '2027-01-01' } };
    expect(summaryRow(dec).sub).toBe('Property tax paid Dec 1 · next: Car registration, January');
    expect(summaryRow({ ...dec, next: { name: 'Holidays', next_due: '2026-12-15' } }).sub).toBe('Property tax paid Dec 1 · next: Holidays, December');
  });
});

describe('one set-aside: the head, the schedule and the payments', () => {
  it('heads with the cost, the yearly figure and the payee, or the planned month', () => {
    expect(headLine(PROPTAX, AS_OF)).toEqual(['$4,210 twice a year', '$8,420 a year', 'County Tax Collector']);
    expect(headLine(HEATER, AS_OF)).toEqual(['$2,200 once', 'Planned for Dec 2028, 26 months away']);
    expect(headLine({ ...HEATER, next_due: '2026-11-01', days_until: 7 }, AS_OF)).toEqual(['$2,200 once', 'Planned for Nov 2026, 1 month away']);
    expect(headLine({ ...HEATER, next_due: '2026-10-01', days_until: -24 }, AS_OF)).toEqual(['$2,200 once', 'Planned for Oct 2026, 24 days ago']);
    expect(headLine(HEATER_PAID, AS_OF)[1]).toBe('Planned for Dec 2028');
  });
  it("words each schedule row from the server's signed days", () => {
    expect(PROPTAX_DETAIL.dues.map((d) => dueSub(d, AS_OF))).toEqual(['In 7 days · first installment', 'In 6 months · second installment']);
    const due = PROPTAX_DETAIL.dues[0];
    expect(dueSub({ ...due, status: 'late', paid_on: '2026-11-20', days_late: 19, days_until: -19 }, AS_OF)).toBe('Paid Nov 20, late · 19 days after · first installment');
    expect(dueSub({ ...due, status: 'late', paid_on: '2026-11-02', days_late: 1, days_until: -19 }, AS_OF)).toBe('Paid Nov 2, late · 1 day after · first installment');
    expect(dueSub({ ...due, status: 'paid', paid_on: '2026-11-01', days_late: 0, days_until: -3 }, AS_OF)).toBe('Paid Nov 1 · first installment');
    expect(dueSub({ ...due, status: 'missed', days_until: -43 }, AS_OF)).toBe('Not paid yet · 6 weeks ago · first installment');
    expect(dueSub({ ...due, status: 'skipped', which: null, days_until: -43 }, AS_OF)).toBe('It was not due');
    expect(dueSub({ ...due, which: null, days_until: 0 }, AS_OF)).toBe('Today');
  });
  it('words the matched payments', () => {
    expect(paymentMeta(PROPTAX_DETAIL.payments[0])).toBe('Apr 10, 2026 · Checking · Taxes · matched to the Apr 10 installment');
    expect(paymentMeta(PROPTAX_DETAIL.payments[1])).toBe('Nov 3, 2025 · Checking · Taxes · matched to the Nov 1 installment, 2 days late');
    expect(paymentMeta(HEATER_PAID.payments[0], HEATER_PAID.name)).toBe('Mar 14, 2028 · House fund · Home and garden · matched to Water heater');
  });
  it('words the head state, with how long ago, the date, and the next installment after a late payment', () => {
    expect(headState(PROPTAX_DETAIL)).toEqual({ tone: 'soon', text: 'Due Nov 1, in 7 days · $110 short · House fund' });
    const missed = { ...PROPTAX_DETAIL, state: 'not_paid' as const, missed_due: '2026-11-01', next_due: '2027-04-10', days_until: 167,
      dues: [{ ...PROPTAX_DETAIL.dues[0], status: 'missed' as const, days_until: -43 }, PROPTAX_DETAIL.dues[1]] };
    expect(headState(missed)).toEqual({ tone: 'soon', text: 'Nov 1 not paid yet · 6 weeks ago · House fund' });
    const late = { ...PROPTAX_DETAIL, state: 'on_track' as const, next_due: '2027-04-10', should_cents: 0,
      dues: [{ ...PROPTAX_DETAIL.dues[0], status: 'late' as const, paid_on: '2026-11-20', days_late: 19, days_until: -19 }, PROPTAX_DETAIL.dues[1]] };
    expect(headState(late)).toEqual({ tone: 'track', text: 'Nov 1 paid Nov 20, late · next Apr 10, 2027' });
    expect(headState(HEATER_PAID)).toEqual({ tone: 'done', text: 'Replaced Mar 14, 2028 · $2,350 paid from House fund' });
    expect(headState(HEATER_DETAIL)).toEqual({ tone: 'track', text: 'On track · nothing due yet · House fund' });
  });
  it("words the fund card in the server's figures", () => {
    expect(fundLines(PROPTAX, AS_OF)).toEqual({ tone: 'soon', lead: '$110 short for Nov 1', detail: '$4,210 due, $4,100 put away',
      context: '$4,212 should be by now: $702 a month, May to October, since the April payment' });
    expect(fundLines(CAMPS, AS_OF)).toEqual({ tone: 'behind', lead: 'Behind by $200', detail: '$600 put away, $800 should be by now',
      context: '$800 should be by now: $200 a month, July to October, since the June payment' });
    expect(fundLines(HEATER, AS_OF)).toEqual({ tone: 'track', lead: 'On track', detail: 'nothing should be by now', context: '$85 a month from November, $2,200 by Dec 2028' });
    expect(fundLines({ ...CAMPS, state: 'on_track', put_away_cents: 90_000, counted_from: null, first_month: '2026-07-01' }, AS_OF)).toEqual({
      tone: 'track', lead: 'On track', detail: '$800 should be by now', context: '$800 should be by now: $200 a month, July to October' });
    expect(fundLines({ ...CAMPS, counted_from: '2026-12-01' }, '2027-02-10').context).toBe('$800 should be by now: $200 a month, January to February, since the December payment');
    const unpaid = { ...PROPTAX, state: 'not_paid' as const, missed_due: '2026-11-01', put_away_cents: 421_000, short_cents: 0 };
    expect(fundLines(unpaid, AS_OF)).toMatchObject({ tone: 'soon', lead: 'Nov 1 not paid yet', detail: '$4,210 due, $4,210 put away' });
    expect(notPaidFund(unpaid)).toBe('House fund keeps the $4,210; "should be by now" keeps counting from April until the installment is paid.');
    expect(notPaidFund(PROPTAX)).toBeNull();
  });
  it("offers the next one in the server's figures, and says so when there is nothing to estimate it from", () => {
    expect(replaceText(HEATER_PAID)).toBe('Water heater replaced Mar 2028 for $2,350. Start setting aside for the next one, about 2042? That is $2,350 over the months to Dec 2042, about $13 a month, with the estimate tag until you know better.');
    expect(replaceText({ ...HEATER_PAID, replace_offer: null })).toBe('Water heater replaced Mar 2028 for $2,350. It has no typical lifespan to estimate the next one from: archive it, or add the next one yourself.');
  });
  it("links Find the payment to the payee over the range the server gives", () => {
    const d = { ...PROPTAX_DETAIL, find_from: '2026-09-17', find_to: '2026-12-14' };
    expect(findHref(d)).toBe('/transactions?dates=custom&from=2026-09-17&to=2026-12-14&q=County+Tax+Collector');
    expect(findHref({ ...d, payee_name: null })).toBe('/transactions?dates=custom&from=2026-09-17&to=2026-12-14');
  });
  it('says what is unchecked before what is sourced, and never sources an unchecked figure', () => {
    const sources = ['Typical water heater lifespan', 'Typical water heater cost'];
    expect(sourceNotes({ to_check: false, cost_to_check: true, sources })).toEqual(['Cost to be checked', 'Lifespan: Typical water heater lifespan']);
    expect(sourceNotes({ to_check: true, cost_to_check: true, sources })).toEqual(['Lifespan to be checked', 'Cost to be checked']);
    expect(sourceNotes({ to_check: false, cost_to_check: false, sources })).toEqual(['Lifespan: Typical water heater lifespan', 'Cost: Typical water heater cost']);
    expect(sourceNotes({ to_check: false, cost_to_check: true })).toEqual(['Cost to be checked']);
  });
});

describe('the form', () => {
  const draft: Draft = { ...emptyDraft(AS_OF), name: 'Home insurance', kind: 'yearly', amount: '1,380', dueMonth: '5', dueDay: '12', payeeKey: 'BIG MUTUAL', payeeName: 'Big Mutual', category: 'insurance' };
  const twice: Draft = { ...draft, kind: 'twice_yearly', amount: '450', dueMonth: '1', dueDay: '15', secondMonth: '7', secondDay: '15' };
  const once: Draft = { ...draft, kind: 'one_off', amount: '2,200', dueYear: '2028', dueMonth: '12', item: 'water_heater', installedYear: '2014' };
  const bodyOf = (d: Draft, from?: Draft) => {
    const r = readDraft(d, AS_OF, from);
    if (!('body' in r)) throw new Error(`unreadable: ${r.error}`);
    return r.body;
  };

  it('reads a draft into the body, and refuses what the server would', () => {
    expect(readDraft(draft, AS_OF)).toEqual({ body: { name: 'Home insurance', kind: 'yearly', amount_cents: 138_000, due_month: 5, due_day: 12, second_month: null, second_day: null,
      due_year: null, account_id: null, payee_key: 'BIG MUTUAL', category: 'insurance', estimate: null, notes: null } });
    expect(readDraft(once, AS_OF)).toEqual({ body: { name: 'Home insurance', kind: 'one_off', amount_cents: 220_000, due_month: 12, due_day: null, second_month: null, second_day: null,
      due_year: 2028, account_id: null, payee_key: 'BIG MUTUAL', category: 'insurance', estimate: { item: 'water_heater', installed_year: 2014, model_year: null, miles: null }, notes: null } });
    expect(readDraft({ ...once, item: 'car', modelYear: '2012', miles: '98,000' }, AS_OF)).toMatchObject({ body: { estimate: { item: 'car', installed_year: null, model_year: 2012, miles: 98_000 } } });
    expect(readDraft({ ...draft, name: ' ' }, AS_OF)).toEqual({ error: 'Give it a name of up to 120 characters.', field: 'name' });
    expect(readDraft({ ...draft, amount: '0' }, AS_OF)).toEqual({ error: 'Enter an amount from $0.01 to $1,000,000.', field: 'amount' });
    expect(readDraft({ ...draft, dueDay: '32' }, AS_OF)).toEqual({ error: 'Choose a day from 1 to 31.', field: 'dueDay' });
    expect(readDraft({ ...twice, secondMonth: '' }, AS_OF)).toEqual({ error: 'Choose a month from 1 to 12.', field: 'secondMonth' });
    expect(readDraft({ ...twice, secondMonth: '1' }, AS_OF)).toEqual({ error: 'The two due dates must differ.', field: 'secondMonth' });
    expect(readDraft({ ...once, dueYear: '2025' }, AS_OF)).toEqual({ error: 'Choose a year from 2026 to 2086.', field: 'dueYear' });
    expect(readDraft({ ...once, installedYear: '20' }, AS_OF)).toEqual({ error: 'Enter the year as four digits.', field: 'installedYear' });
  });
  it('lets a one-off keep a year that has gone by, as the server does, but not take a new one', () => {
    const overdue = { ...once, dueYear: '2025' };
    expect(readDraft(overdue, AS_OF)).toMatchObject({ field: 'dueYear' });
    expect(readDraft(overdue, AS_OF, overdue)).toMatchObject({ body: { due_year: 2025 } });
    expect(readDraft({ ...overdue, dueYear: '2024' }, AS_OF, overdue)).toMatchObject({ field: 'dueYear' });
  });
  it('refuses a one-off due in a month gone by this year, unless an edit leaves the year and month as they were', () => {
    const passed = { error: 'That month has passed. Choose this month or later.', field: 'dueMonth' };
    const sept = { ...once, dueYear: '2026', dueMonth: '9' };
    expect(readDraft(sept, AS_OF)).toEqual(passed);
    expect(readDraft({ ...sept, dueMonth: '10' }, AS_OF)).toMatchObject({ body: { due_year: 2026, due_month: 10 } });     // this month is fine
    expect(readDraft(sept, AS_OF, sept)).toMatchObject({ body: { due_year: 2026, due_month: 9 } });                      // left as it was
    expect(readDraft({ ...sept, dueMonth: '8' }, AS_OF, sept)).toEqual(passed);
    expect(readDraft(sept, AS_OF, { ...sept, dueYear: '2027' })).toEqual(passed);
    expect(readDraft({ ...sept, dueYear: '2027' }, AS_OF)).toMatchObject({ body: { due_year: 2027, due_month: 9 } });
  });
  it('fills the draft from a set-aside', () => {
    expect(draftFrom(PROPTAX)).toMatchObject({ name: 'Property tax', kind: 'twice_yearly', amount: '4,210', dueMonth: '11', dueDay: '1', secondMonth: '4', secondDay: '10', accountId: '21', payeeKey: 'COUNTY TAX COLLECTOR', category: 'taxes' });
    expect(draftFrom(HEATER)).toMatchObject({ kind: 'one_off', amount: '2,200', dueYear: '2028', dueMonth: '12', item: 'water_heater', installedYear: '2014', miles: '' });
  });
  it('sends only what changed, all the due fields when the kind changes, and the estimate only when its inputs moved', () => {
    const base = bodyOf(twice);
    expect(changedBody(base, base)).toEqual({});
    expect(changedBody(bodyOf({ ...twice, amount: '430' }), base)).toEqual({ amount_cents: 43_000 });
    expect(changedBody(bodyOf({ ...twice, accountId: '22' }), base)).toEqual({ account_id: 22 });
    expect(changedBody(bodyOf({ ...twice, secondDay: '20' }), base)).toEqual({ second_day: 20 });
    expect(changedBody(bodyOf({ ...twice, kind: 'yearly', secondMonth: '', secondDay: '' }), base)).toEqual({ kind: 'yearly', due_month: 1, due_day: 15, second_month: null, second_day: null, due_year: null });
    const est = bodyOf(once);
    expect(changedBody(bodyOf({ ...once, name: 'Heater' }), est)).toEqual({ name: 'Heater' });
    expect(changedBody(bodyOf({ ...once, installedYear: '2010' }), est)).toEqual({ estimate: { item: 'water_heater', installed_year: 2010, model_year: null, miles: null } });
    expect(changedBody(bodyOf({ ...once, dueYear: '2030' }), est)).toEqual({ due_year: 2030 });
  });
  it('asks the server for the draft as it will be saved: all of it to add, what changed to edit, an estimate before its amount exists', () => {
    expect(previewRequest(draft, AS_OF)).toEqual({ kind: 'yearly', amount_cents: 138_000, due_month: 5, due_day: 12, second_month: null, second_day: null, due_year: null, estimate: null });
    expect(previewRequest({ ...draft, amount: '' }, AS_OF)).toBeNull();
    const onceNew: Draft = { ...emptyDraft(AS_OF), kind: 'one_off', item: 'water_heater', installedYear: '2014' };
    expect(previewRequest(onceNew, AS_OF)).toEqual({ kind: 'one_off', estimate: { item: 'water_heater', installed_year: 2014, model_year: null, miles: null } });
    expect(previewRequest({ ...onceNew, installedYear: '20' }, AS_OF)).toBeNull();
    expect(previewRequest({ ...onceNew, item: 'other' }, AS_OF)).toBeNull();
    const initial = draftFrom(PROPTAX);
    const edit = { id: 1, was: bodyOf(initial, initial), initial };
    expect(previewRequest(initial, AS_OF, edit)).toEqual({ set_aside_id: 1 });
    expect(previewRequest({ ...initial, amount: '4,300' }, AS_OF, edit)).toEqual({ amount_cents: 430_000, set_aside_id: 1 });
    expect(previewRequest({ ...initial, amount: '' }, AS_OF, edit)).toBeNull();
    const heater = draftFrom(HEATER);
    const heaterEdit = { id: 6, was: bodyOf(heater, heater), initial: heater };
    expect(previewRequest({ ...heater, installedYear: '2010' }, AS_OF, heaterEdit)).toEqual({
      estimate: { item: 'water_heater', installed_year: 2010, model_year: null, miles: null }, amount_cents: 220_000, due_year: 2028, due_month: 12, set_aside_id: 6 });
  });
  it("words the server's preview", () => {
    const pv = { kind: 'yearly' as const, amount_cents: 138_000, monthly_cents: 11_500, yearly_cents: 138_000, first_month: '2026-11-01', next_due: '2027-05-12', months: null };
    expect(previewLines(pv)).toEqual({ when: 'From November · next due May 12, 2027', monthly: '$115 a month', more: [] });
    expect(previewLines({ ...pv, kind: 'twice_yearly', next_due: '2026-11-01', should_cents: 421_200 }).when).toBe('From November · next due Nov 1, 2026');
    expect(previewLines({ ...pv, kind: 'one_off', next_due: '2028-12-01', months: 26, should_cents: 0 })).toEqual({ when: 'From November · planned for Dec 2028', monthly: '$115 a month',
      more: ['Spread over 26 months', 'Nothing should be by now'] });
    expect(previewLines({ ...pv, kind: 'one_off', next_due: null, months: 1, should_cents: 8_500 })).toEqual({ when: 'From November', monthly: '$115 a month', more: ['Spread over 1 month', '$85 should be by now'] });
  });
  it("words the estimate from the server's years and amounts", () => {
    const e = { item: 'water_heater', label: 'Water heater', installed_year: 2014, model_year: null, miles: null, age: 12, miles_per_year: null, lifespan: [10, 15] as [number, number], lifespan_miles: null,
      range: [2024, 2029] as [number, number], decided_by: 'age' as const, planned_year: 2028, due_year: 2028, due_month: 12, cost_range: [150_000, 300_000] as [number, number], replacement_cents: 220_000,
      sale_cents: 0, amount_cents: 220_000, months: 26, first_month: '2026-11-01', monthly_cents: 8_462, sources: [], to_check: false, cost_to_check: true };
    expect(estimateWords(e)).toBe('A water heater usually lasts 10 to 15 years, so 2024 to 2029 from 2014. Steward plans for Dec 2028, a year before the end: $2,200 over the 26 months from November.');
    expect(estimateWords({ ...e, range: [2024, 2026], planned_year: 2026 })).toMatch(/ It is past the usual range already, so Steward plans for this December\.$/);
    const car = { ...e, item: 'car', label: 'Car', installed_year: null, model_year: 2012, lifespan: [12, 15] as [number, number], lifespan_miles: [150_000, 200_000] as [number, number], range: [2024, 2027] as [number, number], miles_per_year: 14_000 };
    expect(estimateWords({ ...car, decided_by: 'miles' })).toContain('at 14,000 miles a year it would pass 200,000 miles by 2027, before its years are up, so miles decide');
    expect(estimateWords({ ...car, decided_by: 'age' })).toContain('From 2012 that is 2024 to 2027; at 14,000 miles a year it would pass 200,000 miles later, so age decides');
    expect(estimateWords({ ...car, miles_per_year: null })).toBe('A car usually goes 12 to 15 years, so 2024 to 2027 from 2012. Steward plans for Dec 2028, a year before the end.');
  });
});
