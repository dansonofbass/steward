// Unit-test fixtures for the investment account page; nothing in the app imports this file.
import type { InvestmentPage, LimitLine } from './api';

export const PAGE: InvestmentPage = {
  account_id: 3, type: 'brokerage_taxable', institution: 'Robo Invest', manual: false,
  sends: { holdings: false, transactions: true },
  year: { start: '2026-01-01', from_jan1: true, start_cents: 17000000, end_cents: 18000000, change_cents: 1000000, change_pct: 5.9,
    put_in_cents: 600000, growth_cents: 400000, estimated: false },
  since: '2025-08-02',
  series: [
    { date: '2025-08-02', balance_cents: 15000000, put_in_cents: 0 },
    { date: '2026-01-01', balance_cents: 17000000, put_in_cents: 200000 },
    { date: '2026-10-13', balance_cents: 18000000, put_in_cents: 800000 },
  ],
  holdings: {
    as_of: '2026-10-13', source: 'feed', filename: null, total_cents: 18000000, unknown: 1, known_cost_cents: 3240,
    mix: [{ class: 'us_stock', cents: 10800000 }, { class: 'other', cents: 7200000 }],
    rows: [
      { id: 1, symbol: 'VTI', name: 'Vanguard Total Stock Market ETF', value_cents: 10800000, ratio_pct: '0.03', ratio_from: 'table', cost_cents: 3240 },
      { id: 2, symbol: 'ACMEX', name: 'Acme Stable Value', value_cents: 7200000, ratio_pct: null, ratio_from: null, cost_cents: null },
    ],
  },
  advisory: { fee_bp: 25, cost_cents: 45000 },
  all_in: { cents: 48240, pct: '0.27' },
  contributions: null,
};

export const page = (over: Partial<InvestmentPage>): InvestmentPage => ({ ...PAGE, ...over });

export const LINE: LimitLine = {
  kind: 'k401', owner: 'jr', name: 'JR', label: '401(k)', year: 2026, limit_cents: 2450000, in_cents: 1800000,
  on_pace_cents: 2180000, short_cents: 270000, raise_pct: 7, maxed: false, estimated: false,
};
