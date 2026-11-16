import type { FactValue } from '../../api/types';
import type { Role } from '../../api/profile';
import { BIRTHDAY_NEEDED, BIRTHDAY_PAST, FILING_NEEDED, NAME_NEEDED, STATE_NEEDED, type Filing } from './copy';

/** myName is null for a person who is neither Person 1 nor Person 2: no name field is shown to them here. */
export type AboutForm = { myName: string | null; jrDob: string; spouseDob: string; state: string; filing: Filing | '' };
export type AboutErrors = Partial<Record<keyof AboutForm, string>>;
type Change = { key: string; value: string };

export function aboutFormFrom(facts: Record<string, FactValue>, myName: string | null): AboutForm {
  return {
    myName,
    jrDob: facts['jr.dob']?.value ?? '',
    spouseDob: facts['spouse.dob']?.value ?? '',
    state: facts.state?.value ?? '',
    filing: (facts.filing_status?.value as Filing | undefined) ?? '',
  };
}

/** The facts that changed and the new name, if any. `only` limits a confirm (decision 2) to that person's birthday. */
export function parseAbout(form: AboutForm, base: AboutForm, today: string, only?: Role): { facts: Change[]; name: string | null } | { errors: AboutErrors } {
  const errors: AboutErrors = {};
  const name = form.myName === null ? null : form.myName.trim();
  if (name !== null && (name === '' || name.length > 80)) errors.myName = NAME_NEEDED;
  const birthday = (value: string, field: 'jrDob' | 'spouseDob') => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) errors[field] = BIRTHDAY_NEEDED;
    else if (value >= today) errors[field] = BIRTHDAY_PAST;
  };
  if (only !== 'spouse') birthday(form.jrDob, 'jrDob');
  if (only !== 'jr') birthday(form.spouseDob, 'spouseDob');
  if (!only) {
    if (!form.state) errors.state = STATE_NEEDED;
    if (!form.filing) errors.filing = FILING_NEEDED;
  }
  if (Object.keys(errors).length > 0) return { errors };
  const facts: Change[] = [];
  const add = (key: string, now: string, was: string) => { if (now !== was) facts.push({ key, value: now }); };
  if (only !== 'spouse') add('jr.dob', form.jrDob, base.jrDob);
  if (only !== 'jr') add('spouse.dob', form.spouseDob, base.spouseDob);
  if (!only) {
    add('state', form.state, base.state);
    add('filing_status', form.filing, base.filing);
  }
  return { facts, name: name !== null && name !== base.myName ? name : null };
}
