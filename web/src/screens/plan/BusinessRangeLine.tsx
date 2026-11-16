import { Briefcase } from 'lucide-react';
import type { ProfitRangeOut } from '../../api/types';
import { Link } from '../../book/links';
import { dollars } from '../../lib/format';
import { BUSINESS_PAGE, PLAN_BUSINESS_ASK, PLAN_BUSINESS_RANGE, PLAN_BUSINESS_YTD } from './copy';

/** D7 on Plan: business profit is a range, never one payment assumed to repeat. The plan tries cash profit; the home
 *  office and mileage only lower tax (final review I3). In January, before a range, it asks for one (M1). */
export function BusinessRangeLine({ range }: { range: ProfitRangeOut }) {
  const year = String(range.year);
  const text = range.entered
    ? PLAN_BUSINESS_RANGE.replace('{year}', year).replace('{low}', dollars(range.cash_low_cents))
      .replace('{high}', dollars(range.cash_high_cents)).replace('{mid}', dollars(range.cash_mid_cents))
    : (range.ask_expect ? PLAN_BUSINESS_ASK : PLAN_BUSINESS_YTD).replace('{year}', year).replace('{ytd}', dollars(range.cash_ytd_cents));
  return (
    <p className="plan-business small">
      <Briefcase className="i" size={20} aria-hidden="true" />
      <span>{text}</span>{' '}
      <Link className="link" to="/business">{BUSINESS_PAGE}</Link>
    </p>
  );
}
