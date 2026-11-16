// The Your home step's form: home value, the mortgage, and the payoff date (calculated or entered). Pure.
import type { FactValue } from '../../api/types';
import { dollarsText, toHundredths } from '../settings/money';
import {
  BALANCE_NEEDED, NEVER_PAID, PAYMENT_NEEDED, PAYOFF_NEEDED, PERCENT_RANGE, RATE_FORMAT, RATE_NEEDED, VALUE_NEEDED,
} from './copy';
import { monthOf, monthsBetween, payoff, payoffYmd, type Month, type Payoff } from './payoff';

export type HomeForm = { value: string; balance: string; rate: string; payment: string; payoff: string; overriding: boolean };
export type HomeErrors = Partial<Record<'value' | 'balance' | 'rate' | 'payment' | 'payoff', string>>;
/** hasAccount: an active mortgage account exists; balanceCents: what it owes (positive), when it has a balance. */
export type Mortgage = { hasAccount: boolean; balanceCents: number | null };
export type HomeSave = { facts: { key: string; value: string }[]; newMortgageCents: number | null };

export const ym = (m: Month): string => payoffYmd(m).slice(0, 7);

/** "2.875" -> 2875 thousandths of a percent and "287.5" basis points (ruling 7); "3" -> 3000 and "300". */
export function parseRate(text: string): { milli: number; bp: string } | { error: string } {
  const m = /^(\d{1,3})(?:\.(\d*))?%?$/.exec(text.trim());
  if (!m) return { error: RATE_NEEDED };
  const [, whole, frac = ''] = m;
  if (frac.length > 3) return { error: RATE_FORMAT };
  const milli = Number(whole) * 1000 + Number(frac.padEnd(3, '0'));
  if (milli > 100_000) return { error: PERCENT_RANGE };
  return { milli, bp: milli % 10 === 0 ? String(milli / 10) : `${Math.floor(milli / 10)}.${milli % 10}` };
}

/** "287.5" -> "2.875", "312" -> "3.12", "300" -> "3". */
export function bpToRate(bp: string): string {
  const milli = Math.round(Number(bp) * 10);
  const frac = String(milli % 1000).padStart(3, '0').replace(/0+$/, '');
  return `${Math.floor(milli / 1000)}${frac ? `.${frac}` : ''}`;
}

function positive(text: string): number | null {
  const p = toHundredths(text);
  return 'error' in p || p.value <= 0 ? null : p.value;
}

/** The payoff the screen shows while someone types; null until the balance, rate and payment are all there. */
export function liveCalc(balanceCents: number | null, rateText: string, paymentText: string, from: Month): Payoff | null {
  if (balanceCents === null) return null;
  const rate = parseRate(rateText);
  const payment = positive(paymentText);
  if ('error' in rate || payment === null) return null;
  return payoff(balanceCents, rate.milli, payment, from);
}

export function homeFormFrom(facts: Record<string, FactValue>, balanceCents: number | null, from: Month): HomeForm {
  const v = (k: string) => facts[k]?.value;
  const form: HomeForm = {
    value: v('home.value_cents') ? dollarsText(Number(v('home.value_cents'))) : '',
    balance: '',
    rate: v('mortgage.rate_bp') ? bpToRate(v('mortgage.rate_bp')!) : '',
    payment: v('mortgage.payment_cents') ? dollarsText(Number(v('mortgage.payment_cents'))) : '',
    payoff: '',
    overriding: false,
  };
  const saved = v('mortgage.payoff_date')?.slice(0, 7);
  if (saved) {
    // A hand-kept balance is as of the month the date was saved, so calculate from there; a linked balance pays down
    // monthly, so calculate from today with the current balance too. Either match, within a month (ruling 9), counts
    // as calculated.
    const savedAt = facts['mortgage.payoff_date']?.as_of;
    const anchors = savedAt ? [monthOf(savedAt), from] : [from];
    const calculated = anchors.some((a) => {
      const calc = liveCalc(balanceCents, form.rate, form.payment, a);
      return calc?.kind === 'months' && Math.abs(monthsBetween(ym(calc), saved)) <= 1;
    });
    if (!calculated) {
      form.overriding = true;
      form.payoff = saved;
    }
  }
  return form;
}

export function parseHome(form: HomeForm, mortgage: Mortgage, from: Month): HomeSave | { errors: HomeErrors } {
  const errors: HomeErrors = {};
  const value = positive(form.value);
  if (value === null) errors.value = VALUE_NEEDED;
  const typed = [form.balance, form.rate, form.payment].some((t) => t.trim() !== '') || (form.overriding && form.payoff !== '');
  if (!mortgage.hasAccount && !typed) {
    return value === null ? { errors } : { facts: [{ key: 'home.value_cents', value: String(value) }], newMortgageCents: null };
  }
  let balance = mortgage.balanceCents;
  if (balance === null && (form.balance.trim() !== '' || !mortgage.hasAccount || !form.overriding)) {
    balance = positive(form.balance);
    if (balance === null) errors.balance = BALANCE_NEEDED;
  }
  const payment = positive(form.payment);
  if (payment === null) errors.payment = PAYMENT_NEEDED;
  let rateBp: string | null = null;
  if (form.rate.trim() !== '') {
    const r = parseRate(form.rate);
    if ('error' in r) errors.rate = r.error;
    else rateBp = r.bp;
  } else if (!form.overriding) {
    errors.rate = RATE_NEEDED;
  }
  let payoffYm: string | null = null;
  if (form.overriding) {
    if (/^\d{4}-(0[1-9]|1[0-2])$/.test(form.payoff)) payoffYm = form.payoff;
    else errors.payoff = PAYOFF_NEEDED;
  } else if (balance !== null && payment !== null && rateBp !== null) {
    const calc = liveCalc(balance, form.rate, form.payment, from);
    if (calc === null || calc.kind === 'never') errors.payment = NEVER_PAID;
    else payoffYm = calc.kind === 'months' ? ym(calc) : ym(from);
  }
  if (Object.keys(errors).length > 0 || value === null || payment === null || payoffYm === null) return { errors };
  const facts = [{ key: 'home.value_cents', value: String(value) }];
  if (rateBp !== null) facts.push({ key: 'mortgage.rate_bp', value: rateBp });
  facts.push({ key: 'mortgage.payment_cents', value: String(payment) }, { key: 'mortgage.payoff_date', value: `${payoffYm}-01` });
  return { facts, newMortgageCents: mortgage.hasAccount ? null : balance };
}
