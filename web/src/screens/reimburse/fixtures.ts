import type { PayerBalance, Reimbursements, TripDetail, TripReason, TripRow, Txn } from '../../api/types';

// Made-up amounts and names only (reimbursable spec's mockup figures).
export const ACME: PayerBalance = {
  id: 1, name: 'Acme', owed_cents: 124035, marked_cents: 203000, repaid_cents: 79000, refunds_cents: 0, settled_cents: 0,
  cleared_cents: 79000, since: '2026-09-01', last_repaid_on: '2026-10-15', settle_category: 'travel',
};
export const GLOBEX: PayerBalance = { ...ACME, id: 2, name: 'Globex', owed_cents: 6035, since: '2026-10-02', settle_category: 'dining' };
const TAXI: Txn = {
  id: 9, account_id: 1, account_name: 'Sapphire', posted_at: '2026-10-25', amount_cents: -1840, raw_description: 'TAXI 22',
  merchant: 'Taxi', category: 'transport', is_business: false, is_transfer: false, business_pct: 0, business_line: null,
  business_source: 'none', category_source: 'correction', reviewed_at: null, from_bank: true, reimburser_id: 1, trip_id: null,
};
export const SUMMARY: Reimbursements = {
  as_of: '2026-10-28',
  payers: [ACME],
  trips: [
    { id: 6, name: 'Austin trip', start: '2026-10-20', end: '2026-10-22', city: 'Austin, TX', reimburser_id: 1, payer: 'Acme',
      count: 4, total_cents: 93620, status: 'waiting' },
    { id: 5, name: 'Chicago trip', start: '2026-09-08', end: '2026-09-10', city: 'Chicago, IL', reimburser_id: 1, payer: 'Acme',
      count: 3, total_cents: 79000, status: 'paid' },
  ],
  singles: [{ ...TAXI, status: 'waiting' }],
};
export const EMPTY_SUMMARY: Reimbursements = { as_of: '2026-10-28', payers: [], trips: [], singles: [] };

const row = (id: number, raw: string, cents: number, group: TripRow['group'], reason: TripReason, ticked: boolean,
  extra: Partial<TripRow> = {}): TripRow => ({
  ...TAXI, id, raw_description: raw, merchant: null, amount_cents: cents, posted_at: '2026-10-07', reimburser_id: null,
  group, reason, ticked, ...extra,
});
export const TRIP_DETAIL: TripDetail = {
  trip: { id: 5, name: 'Chicago trip', start: '2026-10-06', end: '2026-10-09', city: 'Chicago, IL', reimburser_id: 1,
    payer: 'Acme', count: 0, total_cents: 0, status: null },
  rows: [
    row(1, 'UNITED AIRLINES', -42000, 'booked', { why: 'booked' }, true, { posted_at: '2026-08-20' }),
    row(2, 'PALMER HOUSE HOTEL', -61200, 'likely', { why: 'hotel' }, true),
    row(3, 'UBER TRIP', -2840, 'likely', { why: 'ride' }, true, { reimburser_id: 1, trip_id: 5 }),
    row(4, 'PORTILLOS CHICAGO IL', -5580, 'likely', { why: 'says', place: 'Chicago' }, true),
    row(5, 'KROGER #123 COLUMBUS OH', -8000, 'home', { why: 'regular' }, false),
    row(6, 'BRIGHT KIDS DAYCARE', -2500, 'home', { why: 'home_only', category: 'childcare_education' }, false),
    row(7, 'CORNER MART', -1100, 'unsure', { why: 'unsure' }, false),
  ],
};
