// Unit-test data for the import screen; nothing in the app imports this file.
import type { Account } from '../../api/types';
import type { PreviewReply, StagedFile } from './api';
import type { StatementLine } from './statements';
import { initialAnswers, type Row } from './logic';

const account = (id: number, name: string, type: Account['type'], institution: string, source: Account['source']): Account =>
  ({ id, name, type, owner: 'joint', source, institution, is_active: true } as Account);
export const ACCT_CARD = account(1, 'Amex Gold', 'credit', 'Rewards Card', 'simplefin');
export const ACCT_BANK = account(2, 'Mom’s savings', 'savings', 'First CU', 'simplefin');
export const ACCT_MANUAL = account(3, 'Cash box', 'checking', 'Manual', 'manual');
export const ACCT_IRA = account(4, 'IRA 8765', 'traditional_ira', 'Pinecrest Funds', 'manual');

type Opts = Partial<StagedFile> & { negate?: boolean | null; dateQuestion?: boolean };
let n = 0;
export function staged({ negate = null, dateQuestion = false, ...over }: Opts = {}): StagedFile {
  n += 1;
  return {
    token: `f_${n}`, name: `activity (${n}).csv`, bytes: 1000, kind: 'csv', state: 'new', label: null, card: false, rows: 10,
    from: '2024-10-02', to: '2024-12-12', imported_before: null, account_id: null, suggested_by: null,
    layout: {
      id: over.state === 'remembered' ? 4 : null, key: 'h:abc', header: ['Date', 'Description', 'Amount', 'Type'],
      mapping: { date: 0, description: 1, amount: 2 }, negate, date_format: dateQuestion ? null : '%m/%d/%Y',
      reading: dateQuestion ? null : 'month/day/year', sign_fixed: false,
      sign: { credit: { verdict: 'negate', lean: 'positive' }, bank: { verdict: null, lean: 'positive' } },
      date_question: dateQuestion ? { example: '03/04/2024', options: [
        { format: '%m/%d/%Y', label: 'March 4', reading: 'month/day/year' },
        { format: '%d/%m/%Y', label: 'April 3', reading: 'day/month/year' }] } : null,
      sample: [['10/03/2024', "TRADER JOE'S #552", '64.18', 'Sale'], ['10/05/2024', 'PAYMENT THANK YOU', '-500.00', 'Payment']],
    },
    errors: [], unreadable: 0, held: null, left_out: { pending: 0, balance: 0, totals: 0, currency: 0 }, error: null,
    ...over,
    ...(over.label === undefined && over.state === 'remembered' ? { label: 'Rewards Card' } : {}),
  };
}

export const statementLine = (p: Partial<StatementLine> = {}): StatementLine => ({
  id: 41, name: 'Statement_0324.pdf', bytes: 482110, pages: 6, added_by: null, kind: 'text', state: 'ready', error: null,
  error_text: null, label: 'Summit Card Services', statement_kind: 'card', period: { start: '2026-03-01', end: '2026-03-31' },
  rows: 24, holdings: null, balance_cents: null, gap_cents: 0, anyway: false, progress: null, last4: '4417', account_id: null,
  suggested_by: null, imported_before: null, expires_at: '2026-11-06T19:00:00+00:00', removed: false, ...p,
});

export function row(file: StagedFile | null): Row {
  return { key: `k${file?.token ?? 'x'}`, name: file?.name ?? 'x.csv', status: file ? 'ready' : 'error', file, error: null,
    accountId: null, answers: file ? initialAnswers(file) : null, confirmed: false, removed: false };
}

export const PREVIEW: PreviewReply = {
  digest: 'c0ffee', new: 2486, already: 318, simplefin: { n: 92, since: '2024-08-04' }, same: 6, unreadable: 1,
  from: '2022-11-03', to: '2024-08-30', accounts: 3, months: 22,
  files: [{ token: 'f_a', name: 'activity (3).csv', account_id: 1, new: 1102, already: 90, simplefin: 0, same: 2,
    from: '2022-11-03', to: '2024-08-30', errors: [{ row: 12, text: 'Row 12: the date "13/45/2024" isn\'t a date.' }],
    unreadable: 1, held: null, left_out: { pending: 0, balance: 2, totals: 0, currency: 0 } }],
  look: {
    same: [{ token: 'f_a', row: 17, posted_at: '2024-03-02', amount_cents: -450, description: 'COFFEE CORNER',
      match: { where: 'steward', posted_at: '2024-03-01', amount_cents: -450, description: 'COFFEE CORNER', account: 'Amex Gold' } }],
    same_more: 0, already: [{ token: 'f_a', row: 3, posted_at: '2024-01-09', amount_cents: -1200, description: 'CITY PARKING' }],
    already_more: 317,
    simplefin: [{ account_id: 7, account: 'Joint checking', since: '2024-08-04',
      rows: [{ token: 'f_b', row: 1, posted_at: '2024-08-10', amount_cents: -5412, description: 'GREENLEAF MARKET' }], more: 0 }],
  },
};
