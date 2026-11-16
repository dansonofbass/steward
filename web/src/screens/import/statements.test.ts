import { describe, expect, it } from 'vitest';
import { importable, isRetryable, money, monthYear, needsLook, oldGatewayNote, pollEvery, statementTag, type StatementLine } from './statements';

const LINE: StatementLine = {
  id: 41, name: 'Statement_0324.pdf', bytes: 482110, pages: 6, added_by: null, kind: 'text', state: 'ready', error: null,
  error_text: null, label: 'Chase checking', statement_kind: 'bank', period: { start: '2024-03-01', end: '2024-03-31' },
  rows: 42, holdings: null, balance_cents: null, gap_cents: 0, anyway: false, progress: null, last4: '1234', account_id: 12,
  suggested_by: 'hint', imported_before: null, expires_at: '2026-11-07T19:00:00+00:00', removed: false,
};
const at = (p: Partial<StatementLine>) => ({ ...LINE, ...p });

describe('statement lines, word for word', () => {
  it('reads every state in the spec’s words', () => {
    expect(statementTag(LINE, 'answering')).toBe('Chase checking · Mar 2024 · 42 rows · adds up ✓');
    expect(statementTag(at({ state: 'queued', rows: null, pages: null }), 'answering')).toBe('Waiting to be read');
    expect(statementTag(at({ state: 'reading', pages: null }), 'answering')).toBe('Reading…');
    expect(statementTag(at({ state: 'reading', pages: 6 }), 'answering')).toBe('New layout · reading on the gateway…');
    expect(statementTag(at({ state: 'waiting' }), 'waiting')).toBe('Waiting for the gateway');
    expect(statementTag(at({ state: 'waiting' }), 'unpaired')).toBe('Reading this needs the gateway. Pair it in Settings › Chat.');
    // INS-12: paired, but the gateway has no local model for it: say so, not "Pair it" or "Waiting for the gateway"
    expect(statementTag(at({ state: 'waiting', needs_model: true }), 'waiting')).toBe('Reading this needs a local model on the gateway.');
    expect(statementTag(at({ state: 'waiting', needs_model: true }), 'answering')).toBe('Reading this needs a local model on the gateway.');
    expect(statementTag(at({ state: 'layout' }), 'answering')).toBe('Check the layout · 1 look');
    expect(statementTag(at({ state: 'off', gap_cents: 1240 }), 'answering')).toBe('Off by $12.40 · Check rows');
    expect(statementTag(at({ state: 'off', gap_cents: -1240, anyway: true }), 'answering')).toBe('Off by $12.40 · importing anyway');
    expect(statementTag(at({ state: 'off', gap_cents: 0 }), 'answering')).toBe('Check rows');
    expect(statementTag(at({ state: 'off', gap_cents: null }), 'answering')).toBe('Check rows');
    expect(statementTag(at({ state: 'off', gap_cents: null, anyway: true }), 'answering')).toBe('Check rows · importing anyway');
    expect(statementTag(at({ state: 'error', error: 'password', error_text: 'This PDF has a password. Save a copy without one and try again.' }), 'answering'))
      .toBe('This PDF has a password. Save a copy without one and try again.');
    expect(statementTag(at({ state: 'cleared' }), 'answering')).toBe('Cleared after a week · Add again');
  });

  it('appends who added it and an earlier import', () => {
    expect(statementTag(at({ added_by: 'Jane' }), 'answering')).toBe('Chase checking · Mar 2024 · 42 rows · adds up ✓ · Added by Jane');
    expect(statementTag(at({ imported_before: '2026-10-12' }), 'answering')).toBe('Chase checking · Mar 2024 · 42 rows · adds up ✓ · imported on Oct 12');
  });

  it('knows which lines need a look and which can be imported', () => {
    expect([needsLook(at({ state: 'layout' })), needsLook(at({ state: 'off' })), needsLook(LINE)]).toEqual([true, true, false]);
    expect(importable(LINE)).toBe(true);
    expect(importable(at({ account_id: null }))).toBe(false);
    expect(importable(at({ state: 'off', anyway: true }))).toBe(true);
    expect(importable(at({ state: 'off' }))).toBe(false);
    expect(importable(at({ removed: true }))).toBe(false);
  });

  it('reads a scan’s progress and its restart and page lines', () => {
    expect(statementTag(at({ state: 'reading', kind: 'scan', progress: { done: 2, of: 12 } }), 'answering'))
      .toBe('Scanned · reading on the gateway, about 20 s a page · page 3 of 12');
    expect(statementTag(at({ state: 'queued', kind: 'scan', progress: { done: 2, of: 12 } }), 'answering')).toBe('Waiting to be read');
    expect(statementTag(at({ state: 'error', error: 'restarted', error_text: 'Steward restarted on page 7 of 12. Add the file again to finish.' }), 'answering'))
      .toBe('Steward restarted on page 7 of 12. Add the file again to finish.');
  });

  it('asks for the account of a scan instead of showing a gap, until one is chosen', () => {
    const none = at({ kind: 'scan', state: 'ready', account_id: null, needs_account: true, gap_cents: null });
    expect(statementTag(none, 'answering')).toBe('Choose its account to check it');
    expect(statementTag(at({ ...none, state: 'off' }), 'answering')).toBe('Choose its account to check it');
    expect([needsLook(at({ ...none, state: 'off' })), importable(none)]).toEqual([false, false]);
    expect(statementTag(at({ kind: 'scan', account_id: 9, needs_account: false }), 'answering')).toBe('Chase checking · Mar 2024 · 42 rows · adds up ✓');
    expect(statementTag(at({ kind: 'scan', state: 'off', account_id: 9, gap_cents: 689700 }), 'answering')).toBe('Off by $6,897.00 · Check rows');
  });

  it('reads holdings and loan lines', () => {
    expect(statementTag(at({ state: 'holdings', statement_kind: 'retirement' }), 'answering')).toBe('Check the holdings · 1 look');
    expect(statementTag(at({ statement_kind: 'retirement', label: 'Vanguard IRA', rows: 0, holdings: 6 }), 'answering'))
      .toBe('Vanguard IRA · Mar 2024 · 6 holdings · adds up ✓');
    expect(statementTag(at({ statement_kind: 'retirement', label: 'Vanguard IRA', rows: 0, holdings: 1 }), 'answering'))
      .toBe('Vanguard IRA · Mar 2024 · 1 holding · adds up ✓');
    expect(statementTag(at({ statement_kind: 'loan', label: 'Car loan', rows: 0, balance_cents: 841207 }), 'answering'))
      .toBe('Car loan · Mar 2024 · balance $8,412.07');
    expect(needsLook(at({ state: 'holdings' }))).toBe(true);
  });

  it('formats money and months', () => {
    expect([money(1240), money(-123456), monthYear('2024-03-31')]).toEqual(['$12.40', '$1,234.56', 'Mar 2024']);
  });
});

describe('reading on the gateway', () => {
  const list = (states: StatementLine['state'][]) => ({ gateway: 'waiting' as const, statements: states.map((state, i) => at({ id: i, state })) });

  it('polls every 3 s while a line reads, every 30 s while one waits, and not otherwise', () => {
    expect(pollEvery(list(['reading', 'waiting']))).toBe(3000);
    expect(pollEvery(list(['waiting', 'ready']))).toBe(30_000);
    expect(pollEvery(list(['ready', 'error']))).toBe(false);
    expect(pollEvery({ gateway: 'waiting', statements: [at({ state: 'waiting', removed: true })] })).toBe(false);
    expect(pollEvery(undefined)).toBe(false);
  });

  it('offers Try again on a file the gateway could not read, and says which update it needs', () => {
    expect(isRetryable(at({ state: 'error', error: 'read_failed' }))).toBe(true);
    expect(isRetryable(at({ state: 'error', error: 'page_failed' }))).toBe(true);
    expect(isRetryable(at({ state: 'error', error: 'password' }))).toBe(false);
    expect(statementTag(at({ state: 'error', error: 'read_failed', error_text: "The gateway couldn't read this file · Try again" }), 'answering'))
      .toBe("The gateway couldn't read this file · Try again");
    expect(oldGatewayNote('gateway')).toBe('The gateway needs an update to read PDFs.');
    expect(oldGatewayNote('local')).toBe('The gateway needs an update to read new layouts.');
    expect(oldGatewayNote(undefined)).toBe('The gateway needs an update to read new layouts.');
  });
});
