import type { Names } from '../../api/household';
import { dateLabel, dollars, monthLabel } from '../../lib/format';
import type { SectionKey } from '../../lib/profileSections';
import { fromHundredths } from '../settings/money';
import { STATES } from '../settings/states';
import type { FactRow } from './api';
import {
  FILING, FILING_NAME, HEALTH_PREMIUM, HOME_VALUE, MATCH_CAP, MATCH_RATE, PAID_OFF_BY, PAY_K401, PAY_ROTH, PAY_SALARY,
  PAYMENT, RATE, STATE, THEIR_BIRTHDAY, type Filing,
} from './copy';
import { bpToRate } from './home';

export type FactKind = 'date' | 'month' | 'dollars' | 'percent' | 'rate' | 'state' | 'filing';
export type FactField = { key: string; label: string; kind: FactKind };

const ABOUT = (names: Names): FactField[] => [
  { key: 'jr.dob', label: THEIR_BIRTHDAY.replace('{name}', names.jr), kind: 'date' },
  { key: 'spouse.dob', label: THEIR_BIRTHDAY.replace('{name}', names.spouse), kind: 'date' },
  { key: 'state', label: STATE, kind: 'state' },
  { key: 'filing_status', label: FILING, kind: 'filing' },
];
const PAY = (names: Names): FactField[] => [
  { key: 'jr.salary_cents', label: PAY_SALARY.replace('{jr}', names.jr), kind: 'dollars' },
  { key: 'jr.k401_pct_bp', label: PAY_K401, kind: 'percent' },
  { key: 'jr.k401_roth_share_bp', label: PAY_ROTH, kind: 'percent' },
  { key: 'employer.match_rate_bp', label: MATCH_RATE, kind: 'percent' },
  { key: 'employer.match_cap_bp', label: MATCH_CAP, kind: 'percent' },
];
const HOME: FactField[] = [
  { key: 'home.value_cents', label: HOME_VALUE, kind: 'dollars' },
  { key: 'mortgage.rate_bp', label: RATE, kind: 'rate' },
  { key: 'mortgage.payment_cents', label: PAYMENT, kind: 'dollars' },
  { key: 'mortgage.payoff_date', label: PAID_OFF_BY, kind: 'month' },
];

/** The facts a section writes, for Earlier values on its card (spec, The card); null when its answers aren't facts. */
export function sectionFacts(section: SectionKey, names: Names): FactField[] | null {
  switch (section) {
    case 'you': return [...ABOUT(names), ...PAY(names)];
    case 'home': return HOME;
    case 'benefits': return [{ key: 'health.premium_cents', label: HEALTH_PREMIUM, kind: 'dollars' }];
    default: return null;
  }
}

export function factText(kind: FactKind, value: string): string {
  switch (kind) {
    case 'dollars': return dollars(Number(value));
    case 'percent': return `${fromHundredths(Number(value))}%`;
    case 'rate': return `${bpToRate(value)}%`;
    case 'month': return monthLabel(value);
    case 'date': {
      const [y, m, d] = value.split('-').map(Number);
      return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    }
    case 'state': return STATES.find(([code]) => code === value)?.[1] ?? value;
    case 'filing': return FILING_NAME[value as Filing] ?? value;
  }
}

export const historyLine = (kind: FactKind, row: FactRow, today: Date): string =>
  [factText(kind, row.value), dateLabel(row.as_of, today), row.note].filter(Boolean).join(' · ');
