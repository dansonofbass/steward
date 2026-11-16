import { describe, expect, it } from 'vitest';
import { ACCT_BANK, ACCT_CARD, ACCT_MANUAL, row, staged } from './fixtures';
import { contradicted, layoutLabel, monthDay, moveField, negateOf, questions, ready, sent, signCopy, tag, validity } from './logic';

describe('a file row', () => {
  it('tags each state', () => {
    expect(tag(row(staged({ state: 'known', label: 'Chase checking', rows: 1204 })), null)).toBe('Chase checking · 1,204 rows');
    expect(tag(row(staged({ state: 'builtin', label: 'Discover', rows: 3 })), null)).toBe('Discover · 3 rows');
    expect(tag(row(staged({ kind: 'ofx', state: 'known', label: 'OFX', rows: 311, layout: null })), null)).toBe('OFX · 311 rows');
    expect(tag(row(staged({ state: 'remembered', label: 'First CU' })), ACCT_BANK)).toBe('First CU · remembered layout');
    expect(tag(row(staged({ state: 'known', label: 'PayPal', rows: 88, imported_before: '2026-10-12' })), null))
      .toBe('PayPal · 88 rows · imported on Oct 12');
    expect(tag({ ...row(null), status: 'reading' }, null)).toBe('Reading…');
    expect(tag({ ...row(null), status: 'error', error: 'Not a CSV, OFX or QFX file.' }, null)).toBe('Not a CSV, OFX or QFX file.');
  });

  it('counts a new layout’s questions for the picked account', () => {
    const r = row(staged({ state: 'new' }));                         // sign clear for a card, ambiguous for a bank
    expect(tag(r, ACCT_CARD)).toBe('New layout · check the columns');
    expect(tag(r, ACCT_BANK)).toBe('New layout · 1 question');
    const both = row(staged({ state: 'new', dateQuestion: true }));
    expect(questions(both, ACCT_BANK)).toBe(2);
    expect(tag(both, ACCT_BANK)).toBe('New layout · 2 questions');
    expect(tag({ ...r, confirmed: true }, ACCT_CARD)).toBe('Rewards Card · new layout');
  });

  it('pre-selects a clear sign and leaves an ambiguous one empty', () => {
    const r = row(staged({ state: 'new' }));
    expect(negateOf(r, ACCT_CARD)).toBe(true);
    expect(negateOf(r, ACCT_BANK)).toBeNull();
    expect(negateOf(r, null)).toBeNull();
    expect(negateOf({ ...r, answers: { ...r.answers!, negate: false } }, ACCT_CARD)).toBe(false);
    const split = { ...r, answers: { ...r.answers!, mapping: { date: 0, description: 1, debit: 2, credit: 3 } } };
    expect(negateOf(split, ACCT_BANK)).toBe(false);
  });

  it('asks a remembered layout again only when the evidence clearly says the other way', () => {
    const f = staged({ state: 'remembered', negate: false });          // remembered as is; the card verdict is negate
    expect(contradicted(f, ACCT_CARD)).toBe(true);
    expect(contradicted(f, ACCT_BANK)).toBe(false);                   // the bank verdict is unclear
    const r = { ...row(f), answers: { ...row(f).answers!, negate: null } };
    expect(tag(r, ACCT_CARD)).toBe('Rewards Card · 1 question');
    expect(ready({ ...r, accountId: ACCT_CARD.id }, ACCT_CARD)).toBe(false);
    expect(ready({ ...r, accountId: ACCT_CARD.id, answers: { ...r.answers!, negate: true } }, ACCT_CARD)).toBe(true);
  });

  it('is ready once it has an account and every question is answered', () => {
    const r = { ...row(staged({ state: 'new' })), accountId: ACCT_CARD.id };
    expect(ready(r, ACCT_CARD)).toBe(false);                          // not confirmed yet
    expect(ready({ ...r, confirmed: true }, ACCT_CARD)).toBe(true);
    expect(ready({ ...r, confirmed: true, accountId: null }, null)).toBe(false);
    expect(ready({ ...row(null), status: 'error', error: 'x' }, null)).toBe(true);   // left out, never waited on
    expect(ready({ ...r, status: 'expired' }, ACCT_CARD)).toBe(true);
    expect(tag({ ...r, status: 'expired' }, ACCT_CARD)).toBe('');
  });

  it('sends the confirmed layout with the sign it settled on', () => {
    const r = { ...row(staged({ state: 'new' })), accountId: ACCT_CARD.id, confirmed: true };
    expect(sent(r, ACCT_CARD)).toEqual({ mapping: { date: 0, description: 1, amount: 2 }, negate: true, date_format: '%m/%d/%Y' });
    expect(sent(row(staged({ state: 'known' })), ACCT_CARD)).toBeNull();
  });

  it('sends no date format, never an empty one, when the server never dated the column', () => {
    const f = staged({ state: 'new' });
    const undated = { ...f, layout: { ...f.layout!, mapping: { amount: 2 }, date_format: null, reading: null } };
    const r = { ...row(undated), accountId: ACCT_CARD.id, confirmed: true };
    const moved = { ...r, answers: { ...r.answers!, mapping: { date: 0, description: 1, amount: 2 } } };
    expect(sent(moved, ACCT_CARD)?.date_format).toBeNull();
  });
});

describe('the confirm’s rules', () => {
  it('moves a field to the column it was chosen for', () => {
    expect(moveField({ date: 0, description: 1, amount: 2 }, 3, 'amount')).toEqual({ date: 0, description: 1, amount: 3 });
    expect(moveField({ date: 0, description: 1, amount: 2 }, 0, 'description')).toEqual({ description: 0, amount: 2 });
    expect(moveField({ date: 0, description: 1, amount: 2 }, 2, 'ignore')).toEqual({ date: 0, description: 1 });
  });
  it('needs a date, a description and an amount or both money columns', () => {
    expect(validity({ date: 0, description: 1, amount: 2 })).toBe('ok');
    expect(validity({ date: 0, description: 1, debit: 2, credit: 3 })).toBe('ok');
    expect(validity({ date: 0, description: 1, debit: 2 })).toBe('invalid');
  });
  it('words the sign question for a card and for everything else', () => {
    expect(signCopy('credit', 'positive')).toEqual({ legend: 'Purchases look positive in this file. Which way do the signs run?',
      options: ['Purchases are positive', 'Purchases are negative'] });
    expect(signCopy('bank', 'negative').legend).toBe('Money out looks negative in this file. Which way do the signs run?');
    expect(signCopy('bank', null)).toEqual({ legend: 'Which way do the signs run in this file?',
      options: ['Money out is positive', 'Money out is negative'] });
  });
  it('labels a layout by the institution, or the account for a manual one', () => {
    expect(layoutLabel(ACCT_CARD)).toBe('Rewards Card');
    expect(layoutLabel(ACCT_BANK)).toBe('First CU');
    expect(layoutLabel(ACCT_MANUAL)).toBe('Cash box');
    expect(monthDay('2026-10-12')).toBe('Oct 12');
  });
});
