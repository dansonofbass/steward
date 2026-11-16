import type { CostLevel, KidsList } from '../../../api/household';
import { dollars } from '../../../lib/format';
import { CONSEQUENCE, CONSEQUENCE_529, CONSEQUENCE_ALL, CONSEQUENCE_ONE, CONSEQUENCE_ZERO } from '../copy';
import { outlook, roundThousand } from '../outlook';

export type Choice = { birth_year: number; level: CostLevel; share_pct: number; covers_living: boolean;
  balance_cents: number; monthly_cents: number; real_return: number };

/** The line under each kid (spec, The consequence line): the total in today's dollars to the nearest $1,000, and with
 *  a 529 linked, how much of it the 529 is on track to cover. Computed here from the server's table (P16). */
export function consequence(c: Choice, name: string, linked: boolean, table: KidsList['college'], planYear: number): string {
  if (c.share_pct === 0) return CONSEQUENCE_ZERO.replace('{name}', name);
  const o = outlook({ ...c, level: c.level }, planYear, table);
  const first = (o.years === 1 ? CONSEQUENCE_ONE : CONSEQUENCE)
    .replace('{total}', dollars(roundThousand(o.total_cents))).replace('{years}', String(o.years));
  if (!linked) return first;
  const second = o.covered_cents >= o.total_cents ? CONSEQUENCE_ALL.replace('{name}', name)
    : CONSEQUENCE_529.replace('{name}', name).replace('{covered}', dollars(roundThousand(o.covered_cents)));
  return `${first} ${second}`;
}
