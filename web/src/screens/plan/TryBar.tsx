import { dollars } from '../../lib/format';
import type { PlanResult } from './api';
import { COMFORTABLY_AT, NOT_BY_70, TRYBAR_AMOUNT, TRYBAR_ODDS, WAS } from './copy';
import { monthlySpend } from './Headline';

type Props = { result: PlanResult; was: PlanResult | null; pending: boolean; basisCents: number; spendingPct: number };

/** Try changes' bar (plan subpages, Try changes and speed): the Comfortably age with its "was", and the headline's
 *  amount and odds in their compact form. It stays on top while the levers scroll by CSS alone (position: sticky). */
export function TryBar({ result, was, pending, basisCents, spendingPct }: Props) {
  const age = result.comfortable_age;
  const before = was && was.comfortable_age !== age ? was.comfortable_age : undefined;
  const amount = TRYBAR_AMOUNT.replace('{amount}', dollars(monthlySpend(basisCents, spendingPct)));
  return (
    <div className={`trybar${pending ? ' is-pending' : ''}`} data-testid="trybar" aria-live="polite" aria-busy={pending || undefined}>
      <p className="trybar__age" data-testid="age-comfortable">
        <span className="trybar__label">{COMFORTABLY_AT}</span>
        <span className="trybar__n">{age === null ? NOT_BY_70 : age}</span>
        {before !== undefined && <span className="trybar__was">{WAS.replace('{age}', before === null ? NOT_BY_70.toLowerCase() : String(before))}</span>}
      </p>
      <p className="trybar__line">{age === null ? amount : `${amount} · ${TRYBAR_ODDS}`}</p>
    </div>
  );
}
