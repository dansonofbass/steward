// The consequence line's arithmetic (profile spec P16), the same as src/steward/engine/college.py, step for step, so
// the shared fixture (web/src/screens/profile/college_outlook.fixture.json) gives the same cents in both. Computed in the browser from
// GET /api/children's table, so a slider move makes no request.
export type CollegeLevel = { years: number; tuition_fees_cents: number; living_cents: number };
export type CollegeTable = { growth: number; levels: Record<string, CollegeLevel> };
export type OutlookIn = {
  birth_year: number; level: string; share_pct: number; covers_living: boolean;
  balance_cents: number; monthly_cents: number; real_return: number;
};
export type Outlook = { years: number; total_cents: number; covered_cents: number };

export const COLLEGE_START_AGE = 18;
const ENGINE_LEVEL: Record<string, string> = { not_sure: 'in_state_public' };
const halfUp = (x: number) => Math.floor(x + 0.5);

export function outlook(k: OutlookIn, planYear: number, table: CollegeTable): Outlook {
  const lv = table.levels[ENGINE_LEVEL[k.level] ?? k.level];
  const start = k.birth_year + COLLEGE_START_AGE;
  const years: number[] = [];
  for (let y = start; y < start + lv.years; y += 1) if (y >= planYear) years.push(y);
  const perYear = (lv.tuition_fees_cents + (k.covers_living ? lv.living_cents : 0)) * (k.share_pct / 100);
  let total = 0;
  for (const y of years) total += perYear * (1 + table.growth) ** (y - planYear);
  const n = Math.max(0, start - planYear);
  const grow = (1 + k.real_return) ** n;
  const monthlyPart = k.monthly_cents * 12 * (k.real_return !== 0 ? (grow - 1) / k.real_return : n);
  const saved = k.balance_cents * grow + monthlyPart;
  return { years: years.length, total_cents: halfUp(total), covered_cents: halfUp(Math.min(saved, total)) };
}

/** Totals and 529 amounts round to the nearest $1,000 (spec, The consequence line). */
export const roundThousand = (cents: number): number => Math.round(cents / 100_000) * 100_000;
