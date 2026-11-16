import { describe, expect, it } from 'vitest';
import { bpToRate, homeFormFrom, parseHome, parseRate, type HomeForm } from './home';

const FROM = { year: 2026, month: 10 };
const form = (over: Partial<HomeForm> = {}): HomeForm => ({ value: '1,250,000', balance: '', rate: '', payment: '', payoff: '', overriding: false, ...over });
const fact = (value: string) => ({ value, as_of: '2026-10-14', note: null });
const NONE = { hasAccount: false, balanceCents: null };
const LINKED = { hasAccount: true, balanceCents: 57_130_000 };

describe('rates (ruling 7)', () => {
  it('reads up to three decimals and stores basis points with at most one decimal', () => {
    expect(parseRate('2.875')).toEqual({ milli: 2875, bp: '287.5' });
    expect(parseRate('3.25')).toEqual({ milli: 3250, bp: '325' });
    expect(parseRate(' 3 ')).toEqual({ milli: 3000, bp: '300' });
    expect(parseRate('0')).toEqual({ milli: 0, bp: '0' });
    expect(parseRate('2.8755')).toEqual({ error: 'Use at most three decimals, like 2.875.' });
    expect(parseRate('abc')).toEqual({ error: 'Enter the interest rate, like 3.25.' });
    expect(parseRate('101')).toEqual({ error: 'Enter a percentage between 0 and 100.' });
  });
  it('shows stored basis points as a rate', () => {
    expect([bpToRate('287.5'), bpToRate('312'), bpToRate('300'), bpToRate('0')]).toEqual(['2.875', '3.12', '3', '0']);
  });
});

describe('parseHome', () => {
  it('a home with no mortgage saves the value alone', () => {
    expect(parseHome(form(), NONE, FROM)).toEqual({ facts: [{ key: 'home.value_cents', value: '125000000' }], newMortgageCents: null });
  });
  it('with no mortgage account, the typed balance makes one and the payoff date is calculated', () => {
    expect(parseHome(form({ balance: '571,300', rate: '2.875', payment: '2,680' }), NONE, FROM)).toEqual({
      facts: [
        { key: 'home.value_cents', value: '125000000' },
        { key: 'mortgage.rate_bp', value: '287.5' },
        { key: 'mortgage.payment_cents', value: '268000' },
        { key: 'mortgage.payoff_date', value: '2051-09-01' },
      ],
      newMortgageCents: 57_130_000,
    });
  });
  it('a linked mortgage gives the balance, so no account is made', () => {
    const saved = parseHome(form({ rate: '2.875', payment: '2,680' }), LINKED, FROM);
    expect(saved).toMatchObject({ newMortgageCents: null });
    expect('facts' in saved && saved.facts.at(-1)).toEqual({ key: 'mortgage.payoff_date', value: '2051-09-01' });
  });
  it('an entered date wins, and the rate may then be left blank', () => {
    expect(parseHome(form({ payment: '2,680', overriding: true, payoff: '2047-06' }), LINKED, FROM)).toEqual({
      facts: [
        { key: 'home.value_cents', value: '125000000' },
        { key: 'mortgage.payment_cents', value: '268000' },
        { key: 'mortgage.payoff_date', value: '2047-06-01' },
      ],
      newMortgageCents: null,
    });
  });
  it('a payment that never pays it off is refused by the payment', () => {
    expect(parseHome(form({ rate: '2.875', payment: '1,000' }), LINKED, FROM)).toEqual({ errors: {
      payment: 'At this rate and payment the balance never goes down. Check the payment, or enter a date.',
    } });
  });
  it('says what is missing in plain words', () => {
    expect(parseHome(form({ value: '', rate: '2.8755', payment: '2,680' }), NONE, FROM)).toEqual({ errors: {
      value: 'Enter what the home would sell for today.',
      balance: 'Enter the balance from your latest statement.',
      rate: 'Use at most three decimals, like 2.875.',
    } });
    expect(parseHome(form({ overriding: true, payoff: '' , payment: '2,680' }), LINKED, FROM)).toEqual({ errors: {
      payoff: 'Choose the month the mortgage is paid off.',
    } });
    expect(parseHome(form({ overriding: true, payoff: '2047-13', payment: '2,680' }), LINKED, FROM)).toEqual({ errors: {
      payoff: 'Choose the month the mortgage is paid off.',
    } });
  });
});

describe('homeFormFrom', () => {
  const facts = { 'home.value_cents': fact('125000000'), 'mortgage.rate_bp': fact('287.5'), 'mortgage.payment_cents': fact('268000') };
  it('a saved date that matches the calculation opens as calculated', () => {
    expect(homeFormFrom({ ...facts, 'mortgage.payoff_date': fact('2051-09-01') }, 57_130_000, FROM))
      .toEqual({ value: '1,250,000', balance: '', rate: '2.875', payment: '2,680', payoff: '', overriding: false });
  });
  it('a saved date that differs opens as entered', () => {
    expect(homeFormFrom({ ...facts, 'mortgage.payoff_date': fact('2047-06-01') }, 57_130_000, FROM))
      .toMatchObject({ overriding: true, payoff: '2047-06' });
  });
  it('a calculated date saved in October still opens as calculated in November', () => {
    const NOV = { year: 2026, month: 11 };
    expect(homeFormFrom({ ...facts, 'mortgage.payoff_date': fact('2051-09-01') }, 57_130_000, NOV))
      .toMatchObject({ overriding: false, payoff: '' });
  });
  it('a date entered five years from the calculation still opens as entered a month later', () => {
    const NOV = { year: 2026, month: 11 };
    expect(homeFormFrom({ ...facts, 'mortgage.payoff_date': fact('2046-09-01') }, 57_130_000, NOV))
      .toMatchObject({ overriding: true, payoff: '2046-09' });
  });
  it('a linked balance that paid down in a later month still opens as calculated', () => {
    const DEC = { year: 2026, month: 12 };
    // Saved in October at $571,300; by December the linked balance is lower, so the date from today is the match.
    expect(homeFormFrom({ ...facts, 'mortgage.payoff_date': fact('2051-09-01') }, 56_800_000, DEC))
      .toMatchObject({ overriding: false, payoff: '' });
  });
  it('a linked balance still reads a genuinely different saved date as entered', () => {
    const DEC = { year: 2026, month: 12 };
    expect(homeFormFrom({ ...facts, 'mortgage.payoff_date': fact('2047-06-01') }, 56_800_000, DEC))
      .toMatchObject({ overriding: true, payoff: '2047-06' });
  });
  it('an empty vault opens empty', () => {
    expect(homeFormFrom({}, null, FROM)).toEqual({ value: '', balance: '', rate: '', payment: '', payoff: '', overriding: false });
  });
});
