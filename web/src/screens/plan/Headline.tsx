import { dollars } from '../../lib/format';
import type { PlanResult } from './api';
import { HEADLINE, HEADLINE_NONE, HEADLINE_ODDS, HEADLINE_NONE_NEXT } from './copy';

/** What a month of retirement spending is, in today's dollars, to the nearest $100: the spending basis times the
 *  Spending in retirement lever. */
export function monthlySpend(basisCents: number, pct: number): number {
  return Math.round((basisCents * pct) / 100 / 12 / 10_000) * 10_000;
}

type Props = { result: PlanResult; basisCents: number; spendingPct: number; younger: string; pending?: boolean };

/** Roadmap 14, the Plan in one sentence (JR, Oct 28): the Comfortably age, what it lets you spend each month in today's
 *  dollars, and the odds behind it. The odds are the Comfortably test itself (9 of 10 simulated market histories last
 *  until the younger is 95), so nothing new is worked out. It follows the levers as they move. */
export function Headline({ result, basisCents, spendingPct, younger, pending = false }: Props) {
  const amount = dollars(monthlySpend(basisCents, spendingPct));
  return (
    <div className={`plan-headline${pending ? ' is-pending' : ''}`} data-testid="plan-headline">
      {result.comfortable_age === null ? (
        <>
          <p className="plan-headline__main">{HEADLINE_NONE.replace('{amount}', amount)}</p>
          <p className="plan-headline__odds">{HEADLINE_NONE_NEXT}</p>
        </>
      ) : (
        <>
          <p className="plan-headline__main">{HEADLINE.replace('{age}', String(result.comfortable_age)).replace('{amount}', amount)}</p>
          <p className="plan-headline__odds">{HEADLINE_ODDS.replace('{younger}', younger)}</p>
        </>
      )}
    </div>
  );
}
