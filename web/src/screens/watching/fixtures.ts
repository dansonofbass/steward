// Unit-test data for the watching screens, from docs/design/watching/README.md "Margaret's flags". Nothing in the app
// imports this file.
import type { FlagList, FlagPage, FlagRow, Ran, WatchSettings } from './api';

export const PARENT = { slug: 'margaret-ellis', name: 'Margaret Ellis', kind: 'parent' as const,
  owners: [{ key: 'margaret', label: 'Margaret' }, { key: 'robert-husband', label: 'Robert (husband)' }, { key: 'joint', label: 'Joint' }] };
export const RAN: Ran = {
  short: 'Checked today, 6:12 AM', line: 'The checks ran today at 6:12 AM, after the bank feed sync.',
  home_empty: 'checked today, 6:12 AM, after the bank feed sync',
  empty: 'The checks ran today at 6:12 AM over 14 new transactions in 3 accounts.',
};
const row = (r: Partial<FlagRow> & Pick<FlagRow, 'id' | 'check' | 'check_label' | 'summary'>): FlagRow => ({
  icon: 'flag', severity: 'normal', urgent: false, status: 'open', status_label: 'Open', by: null, note: null, note_by: null,
  title: r.summary, place: 'Joint checking', when: 'Sat, Oct 17', flagged: 'Flagged Oct 18', amount_cents: 0, done: false,
  account_id: 1, ...r,
});
export const GIFT = row({ id: 41, check: 'scam', check_label: 'Scam pattern', icon: 'octagon-alert', severity: 'urgent', urgent: true,
  summary: '$500.00 gift card at CVS Pharmacy', amount_cents: 50000 });
export const PREMIUM = row({ id: 39, check: 'premium', check_label: 'Missed premium', icon: 'calendar-x', severity: 'urgent', urgent: true,
  summary: "the Evergreen Mutual long-term care premium hasn't left Joint checking", title: "Long-term care premium hasn't left",
  place: 'Long-term care', when: 'Due Mon, Oct 12', flagged: 'Flagged Oct 17', amount_cents: 21200 });
export const ZELLE = row({ id: 38, check: 'payee', check_label: 'New payee', icon: 'user-plus', severity: 'urgent', urgent: true,
  summary: '$1,200.00 by Zelle to J. Smith', when: 'Fri, Oct 16', flagged: 'Flagged Oct 17', amount_cents: 120000 });
export const LOW = row({ id: 43, check: 'low', check_label: 'Low balance', icon: 'trending-down',
  summary: 'Way2Save savings is under its $25,000.00 floor', place: 'Way2Save savings', when: 'Since Sun, Oct 18',
  flagged: 'Flagged Oct 19', amount_cents: 2248010, account_id: 2 });
export const STREAMBOX = row({ id: 42, check: 'monthly', check_label: 'New monthly charge', icon: 'repeat',
  summary: 'StreamBox, $15.99 on Sep 18 and Oct 18', place: 'Citi card', when: 'Sun, Oct 18', flagged: 'Flagged Oct 19',
  amount_cents: 1599, account_id: 3 });
export const RALPHS = row({ id: 36, check: 'duplicate', check_label: 'Duplicate', icon: 'copy', status: 'checking',
  status_label: 'Still checking', by: 'JR, Oct 15', note: 'Asked Margaret about two trips to Ralphs. Waiting to hear back.',
  note_by: 'JR', summary: '$64.18 at Ralphs on Oct 13 and again on Oct 14', title: '$64.18 at Ralphs, twice',
  place: 'Citi card', when: 'Wed, Oct 14', flagged: 'Flagged Oct 15', amount_cents: 6418, account_id: 3 });
export const DENTIST = row({ id: 33, check: 'large', check_label: 'Large amount', icon: 'banknote', status: 'expected',
  status_label: 'Expected', by: 'Robin, Oct 9', note: "Margaret's crown. Margaret told me about it on Sunday.", note_by: 'Robin',
  summary: '$640.00 to Brea Family Dental', when: 'Thu, Oct 8', flagged: 'Flagged Oct 9', amount_cents: 64000, done: true });
export const OPEN_ROWS = [GIFT, PREMIUM, ZELLE, LOW, STREAMBOX, RALPHS];
export const LIST: FlagList = {
  show: 'open', flags: OPEN_ROWS, counts: { open: 6, done: 3 },
  checks: [{ check: 'scam', label: 'Scam pattern', count: 1 }, { check: 'premium', label: 'Missed premium', count: 1 },
    { check: 'payee', label: 'New payee', count: 1 }, { check: 'monthly', label: 'New monthly charge', count: 1 },
    { check: 'duplicate', label: 'Duplicate', count: 1 }, { check: 'low', label: 'Low balance', count: 1 }],
  accounts: [{ id: 3, name: 'Citi card' }, { id: 1, name: 'Joint checking' }, { id: 2, name: 'Way2Save savings' }],
  next_offset: null, ran: RAN, mail_ready: true, can_edit: true,
};
export const DONE_LIST: FlagList = { ...LIST, show: 'done', flags: [DENTIST], checks: [{ check: 'large', label: 'Large amount', count: 1 }] };
export const GIFT_PAGE: FlagPage = {
  ...GIFT,
  why: 'This check flags every gift card, wire transfer, crypto exchange, money-transfer service and remote computer support payment, because those are the payments scammers ask for.',
  fact: '$500.00 gift card at CVS Pharmacy, from Joint checking.',
  also: [{ check: 'large', label: 'Large amount', icon: 'banknote', detail: '$500.00 or more' }],
  flagged_at: '2026-10-18T13:12:00+00:00', status_at: null,
  transaction: { removed: false, id: 901, payee: 'CVS Pharmacy', amount_cents: 50000, date_label: 'Sat, Oct 17, 2026', account: 'Joint checking',
    joint_names: 'Margaret and Robert (husband)', raw: 'CVS/PHARMACY #09812 GIFT CARD FULLERTON CA', category_label: 'Shopping' },
  others: [],
  earlier: { heading: 'Earlier at CVS Pharmacy', line: '3 purchases in the last 12 months, from $8.20 to $61.35. None were gift cards.', rows: [
    { name: 'CVS Pharmacy', amount_cents: 2347, meta: 'Oct 2 · Joint checking' }, { name: 'CVS Pharmacy', amount_cents: 6135, meta: 'Sep 14 · Joint checking' },
    { name: 'CVS Pharmacy', amount_cents: 820, meta: 'Aug 29 · Citi card' }] },
  payments: [], related: { id: 1, name: 'Joint checking', sub: 'Wells Fargo Checking ••4417', amount_cents: 821455, status: 'confirmed' },
  related_line: null,
  expected: { scopes: [], fixed: "This marks only this flag. Gift cards, wires and money transfers are always flagged, whoever they're paid to.",
    help: 'Nothing wrong. The flag moves to Done. Payments like this are still flagged.' },
  expected_note: null, known: null,
  history: [{ id: 'e2', icon: 'mail', text: 'Urgent email sent to JR and Robin', note: null, at: '2026-10-18T13:14:00+00:00' },
    { id: 'e1', icon: 'flag', text: 'Flagged by the checks after the bank feed sync', note: null, at: '2026-10-18T13:12:00+00:00' }],
  can_edit: true, viewer_line: null,
};
export const DENTIST_PAGE: FlagPage = {
  ...GIFT_PAGE, ...DENTIST, status: 'open', status_label: 'Open', by: null, note: null, note_by: null, done: false,
  why: 'This check flags any payment of $500.00 or more, the amount set in Settings → Watching.',
  fact: '$640.00 to Brea Family Dental, from Joint checking.',
  also: [{ check: 'payee', label: 'New payee', icon: 'user-plus', detail: 'not paid in the last 18 months' }],
  transaction: { ...GIFT_PAGE.transaction!, id: 902, payee: 'Brea Family Dental', amount_cents: 64000, date_label: 'Thu, Oct 8, 2026',
    raw: 'BREA FAMILY DENTAL', category_label: 'Health' },
  earlier: { heading: 'Earlier at Brea Family Dental', line: 'No earlier payments to Brea Family Dental in the last 12 months.', rows: [] },
  expected: { scopes: [
    { key: 'about', title: 'Not for about this amount', line: 'Brea Family Dental, $480 to $800. A bigger payment is still flagged.' },
    { key: 'any', title: 'Not for any amount', line: "Brea Family Dental isn't flagged again as a new payee, a large amount, unusual or a new monthly charge." },
    { key: 'this', title: 'Yes, this one only', line: 'The next payment to Brea Family Dental of $500 or more is flagged again.' }],
    fixed: null, help: 'Nothing wrong. The flag moves to Done. You choose whether Brea Family Dental is flagged again.' },
  history: [{ id: 'e1', icon: 'flag', text: 'Flagged by the checks after the bank feed sync', note: null, at: '2026-10-09T13:12:00+00:00' }],
};
export const PREMIUM_PAGE: FlagPage = {
  ...GIFT_PAGE, ...PREMIUM,
  why: "This check flags an insurance premium that hasn't left 5 days after its usual day, because a missed premium can end a policy.",
  fact: "the Evergreen Mutual long-term care premium, $212.00, usually leaves Joint checking around the 10th. Oct 10 was a Saturday, so it was due Mon, Oct 12. It hasn't left as of Oct 17.",
  also: [], transaction: null, earlier: null,
  payments: [{ name: 'EVERGREEN MUTUAL LTC PREM', amount_cents: 21200, meta: 'Thu, Sep 10 · Joint checking' },
    { name: 'EVERGREEN MUTUAL LTC PREM', amount_cents: 21200, meta: 'Mon, Aug 10 · Joint checking' }],
  related: { id: 12, name: 'Long-term care', sub: 'Evergreen Mutual · policy ••7730', amount_cents: 21200, status: 'needs_checking' },
  related_line: 'Policy ••7730 · Evergreen Mutual: (800) 555-0142',
  expected: { scopes: [], fixed: 'This marks only this flag. A missing deposit or a missed premium is always flagged.', help: 'Nothing wrong. The flag moves to Done.' },
  expected_note: 'Expected here means "not due this month". If the premium changed (paid yearly, a new amount, a new account), edit the item so the check looks for the right payment.',
};

export const SETTINGS: WatchSettings = {
  large_cents: 50000, cash_alert_floor_cents: 20000, default_cash_floor_cents: 20000, default_cents: 50000,
  floors: [
    { item_id: 1, name: 'Joint checking', sub: 'Wells Fargo ••4417 · now $8,214.55', balance_cents: 821455, floor_cents: 200000, under: false },
    { item_id: 2, name: 'Way2Save savings', sub: 'Wells Fargo ••4425 · now $22,480.10', balance_cents: 2248010, floor_cents: 2500000, under: true },
    { item_id: 3, name: '12-month CD', sub: 'Pacific Western Credit Union ••0072 · statements', balance_cents: null, floor_cents: null, under: false }],
  known: [{ id: 4, payee: 'Brea Family Dental', range: '$480 to $800', added: 'Robin, Oct 9, from a Large amount flag', note: "Margaret's crown." }],
  mail: { ready: true, last_sent: 'Last sent today at 7:00 AM (daily summary to JR and Robin).', failure: null },
  people: [
    { user_id: 1, name: 'JR', role: 'manager', role_label: 'Manager', urgent: true, summary: true, can_change: true, is_me: true },
    { user_id: 2, name: 'Robin', role: 'manager', role_label: 'Manager', urgent: true, summary: true, can_change: false, is_me: false },
    { user_id: 3, name: 'Tess', role: 'viewer', role_label: 'Viewer', urgent: false, summary: false, can_change: true, is_me: false }],
  can_edit: true,
};
