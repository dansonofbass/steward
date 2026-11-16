import { api, json } from '../../api/client';
import type { FactValue } from '../../api/types';
import { dollarsText, fromHundredths, toHundredths } from '../settings/money';
import { PERCENT_RANGE, PREMIUM_NEEDED, SALARY_NEEDED } from './copy';

export type FactInput = { key: string; value: string; note: string };
type Fact = Omit<FactInput, 'note'>;
type Facts = Record<string, FactValue>;

/** Matches plan_inputs.SUGGESTED_HEALTH_PREMIUM_CENTS: $1,400 a month (M2-B ruling 14). */
export const SUGGESTED_HEALTH_CENTS = 1_680_000;
export const savedNote = (name: string) => `Saved by ${name}`;
const CONFIRMED = 'Confirmed by ';
export const confirmedNote = (name: string) => CONFIRMED + name;
export const confirmedBy = (note: string | null | undefined): string | undefined =>
  (note?.startsWith(CONFIRMED) ? note.slice(CONFIRMED.length) || undefined : undefined);

/** One POST per fact, in order. Facts keep their history, so a retry after a failure only adds rows. */
export async function saveFacts(facts: FactInput[]): Promise<void> {
  for (const f of facts) await api('/api/facts', json(f));
}

const shown = (facts: Facts, key: string, fallback = '') => (facts[key] ? fromHundredths(Number(facts[key].value)) : fallback);
const shownDollars = (facts: Facts, key: string) => (facts[key] ? dollarsText(Number(facts[key].value)) : '');

function amount(text: string, needed: string, positive: boolean): number | string {
  if (text.trim() === '') return needed;
  const p = toHundredths(text);
  if ('error' in p) return p.error;
  if (p.value < 0 || (positive && p.value === 0)) return needed;
  return p.value;
}

function percent(text: string, empty: number | null): number | string {
  if (text.trim() === '' && empty !== null) return empty;
  const p = toHundredths(text);
  if ('error' in p) return PERCENT_RANGE;
  return p.value < 0 || p.value > 10_000 ? PERCENT_RANGE : p.value;
}

export type PayForm = { salary: string; k401: string; roth: string; matchRate: string; matchCap: string };

export function payFormFrom(facts: Facts): PayForm {
  return {
    salary: shownDollars(facts, 'jr.salary_cents'), k401: shown(facts, 'jr.k401_pct_bp'), roth: shown(facts, 'jr.k401_roth_share_bp', '0'),
    matchRate: shown(facts, 'employer.match_rate_bp'), matchCap: shown(facts, 'employer.match_cap_bp'),
  };
}

export function parsePay(form: PayForm, jr: string): { facts: Fact[] } | { errors: Partial<Record<keyof PayForm, string>> } {
  const values = {
    salary: amount(form.salary, SALARY_NEEDED.replace('{jr}', jr), true),
    k401: percent(form.k401, null), roth: percent(form.roth, 0),
    matchRate: percent(form.matchRate, null), matchCap: percent(form.matchCap, null),
  };
  const errors = Object.fromEntries(Object.entries(values).filter(([, v]) => typeof v === 'string')) as Partial<Record<keyof PayForm, string>>;
  if (Object.keys(errors).length > 0) return { errors };
  const n = values as Record<keyof PayForm, number>;
  return { facts: [
    { key: 'jr.salary_cents', value: String(n.salary) },
    { key: 'jr.k401_pct_bp', value: String(n.k401) },
    { key: 'jr.k401_roth_share_bp', value: String(n.roth) },
    { key: 'employer.match_rate_bp', value: String(n.matchRate) },
    { key: 'employer.match_cap_bp', value: String(n.matchCap) },
  ] };
}

/** The dollar figures under the 401(k) field and the match sentence, in cents; null until the inputs read. */
export function payPreview(form: PayForm): { contribution: number | null; match: number | null } {
  const salary = toHundredths(form.salary);
  const k401 = toHundredths(form.k401);
  if ('error' in salary || salary.value <= 0 || 'error' in k401 || k401.value < 0 || k401.value > 10_000) return { contribution: null, match: null };
  const contribution = Math.round((salary.value * k401.value) / 10_000);
  const rate = toHundredths(form.matchRate);
  const cap = toHundredths(form.matchCap);
  if ('error' in rate || 'error' in cap || rate.value < 0 || cap.value < 0 || rate.value > 10_000 || cap.value > 10_000) return { contribution, match: null };
  return { contribution, match: Math.round((((salary.value * Math.min(k401.value, cap.value)) / 10_000) * rate.value) / 10_000) };
}

export function parsePremium(text: string): { cents: number } | { error: string } {
  const v = amount(text, PREMIUM_NEEDED, false);
  return typeof v === 'string' ? { error: v } : { cents: v };
}
