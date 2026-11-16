import type { FactValue } from '../../api/types';
import type { Names } from './api';
import { YOUNGER_OF_YOU } from './copy';

export type People = { names: Names; planYear: number; jrAge: number; spouseAge: number; younger: string };

/** Ages in the plan year, as the engine counts them (plan year minus birth year), and whose 95th birthday ends the plan. */
export function peopleFrom(names: Names, facts: Record<string, FactValue> | undefined, planYear: number, jrAgeHint: number): People {
  const jr = facts?.['jr.dob']?.value;
  const sp = facts?.['spouse.dob']?.value;
  const jrAge = jr ? planYear - Number(jr.slice(0, 4)) : jrAgeHint;
  const spouseAge = sp ? planYear - Number(sp.slice(0, 4)) : jrAge;
  const younger = jr && sp ? (sp > jr ? names.spouse : names.jr) : YOUNGER_OF_YOU;
  return { names, planYear, jrAge, spouseAge, younger };
}
