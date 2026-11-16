import { ChevronRight, CircleAlert, CircleCheck, CircleDashed, type LucideIcon } from 'lucide-react';
import type { FixedRow, FixedTone, SpendingMonth } from '../../api/types';
import { Link } from '../../book/links';
import { label } from '../../lib/categories';
import { dollars } from '../../lib/format';
import { drillHref } from '../cashflow/months';
import * as C from './copy';
import { GivingOutside } from './GivingOutside';
import { fixedAmount, fixedText } from './model';

const TONE_ICON: Record<FixedTone, LucideIcon | null> = { check: CircleCheck, ring: CircleDashed, amber: CircleAlert, quiet: null };

/** One Bill or Commitment (spec, Cases and copy). The tone is the server's: a check means paid and nothing else, in
 *  neutral ink; a dashed ring is waiting or so far; amber is a Bill's only; quiet has no icon. The name opens the
 *  category (its link covers the row); See charges, on a Bill over usual, opens that month's transactions. */
export function FixedLine({ r, m, canEdit }: { r: FixedRow; m: SpendingMonth; canEdit: boolean }) {
  const Icon = TONE_ICON[r.tone];
  const amount = fixedAmount(r);
  return (
    <div className={`sp-fixed sp-fixed--row is-${r.tone}`} data-testid="fixed-row" data-category={r.category} data-state={r.state}>
      {Icon ? <Icon className="i" size={24} aria-hidden="true" /> : <span className="i" aria-hidden="true" />}
      <Link className="sp-fixed__name sp-fixed__go" to={`/spending/${r.category}?month=${m.month}`}>{label(r.category)}</Link>
      <span className="sp-fixed__sub">
        {fixedText(r)}
        {r.kind === 'fixed' && r.state === 'over' && <>{' · '}<Link className="link sp-fixed__see" to={drillHref(m.month, r.category, m.as_of)}>{C.SEE_CHARGES}</Link></>}
        {r.outside_cents !== undefined && <GivingOutside cents={r.outside_cents} canEdit={canEdit} />}
      </span>
      <span className="money money--m">{amount === null ? '' : dollars(amount)}</span>
      <ChevronRight className="i sp-fixed__chev" size={20} aria-hidden="true" />
    </div>
  );
}
