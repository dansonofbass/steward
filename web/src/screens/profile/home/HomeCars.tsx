import { House } from 'lucide-react';
import type { QueryClient } from '@tanstack/react-query';
import { dollars, money, monthLabel } from '../../../lib/format';
import { bpToRate } from '../home';
import { useProfileHome, type HomeData } from '../api';
import { CARD_LOAN, CARD_PAYMENT, CARD_PAYOFF, CARD_RATE, CARD_THING, CARD_WHERE, STEP_CARS, STEP_HOMES, STEP_MORTGAGES, STEP_OWN } from '../copy';
import type { SectionDef } from '../sections';
import { Cars } from './Cars';
import { Homes } from './Homes';
import { Mortgages } from './Mortgages';
import { Own, ownsNo } from './Own';

const no = (qc: QueryClient) => ownsNo(qc.getQueryData<HomeData>(['profile-home']));
const value = (c: number | null) => (c === null ? '' : money(c));

function useHomeSummary(): string[] | null {
  const h = useProfileHome().data;
  if (!h) return null;
  const lines: string[] = [];
  for (const p of h.properties) {
    const where = p.account_id === h.where_you_live;
    lines.push((where ? CARD_WHERE : CARD_THING).replace('{name}', p.name).replace('{value}', value(p.value_cents)));
    const m = p.mortgage;
    if (m && where) {
      lines.push([m.name,
        m.rate_bp === null ? null : CARD_RATE.replace('{rate}', bpToRate(String(m.rate_bp))),
        m.payment_cents ? CARD_PAYMENT.replace('{payment}', dollars(m.payment_cents)) : null,
        m.payoff_date ? CARD_PAYOFF.replace('{month}', monthLabel(m.payoff_date)) : null].filter(Boolean).join(' · '));
    } else if (m) {
      lines.push(m.name);
    }
  }
  for (const c of h.cars) {
    lines.push(CARD_THING.replace('{name}', c.name).replace('{value}', value(c.value_cents))
      + (c.loan ? ` · ${CARD_LOAN.replace('{loan}', c.loan.name).replace('{balance}', value(c.loan.balance_cents))}` : ''));
  }
  return lines;
}

/** Profile's third section (decision 4, P19-P23). No skips Homes and Mortgages; cars never block done. */
export const HOME_SECTION: SectionDef = {
  icon: House,
  steps: [
    { key: 'own', title: () => STEP_OWN, Body: Own },
    { key: 'homes', title: () => STEP_HOMES, Body: Homes, skip: no },
    { key: 'mortgages', title: () => STEP_MORTGAGES, Body: Mortgages, skip: no },
    { key: 'cars', title: () => STEP_CARS, Body: Cars },
  ],
  useSummary: useHomeSummary,
};
