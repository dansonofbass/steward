import { ApiError } from '../../api/client';
import type { AccountType, Owner, OwnerOption } from '../../api/types';
import { BUSINESS, PERSON_1, PERSON_2, PERSON_JOINT } from '../../lib/copy';

export const failure = (e: unknown) => (e instanceof ApiError ? e.message : "That didn't finish. Try again.");

// Every type a person can choose; 'unknown' is only what the bank sends before someone decides.
export const TYPE_OPTIONS: { value: AccountType; label: string }[] = [
  { value: 'checking', label: 'Checking' },
  { value: 'savings', label: 'Savings' },
  { value: 'credit', label: 'Credit card' },
  { value: 'brokerage_taxable', label: 'Brokerage' },
  { value: 'k401', label: '401(k)' },
  { value: 'roth_ira', label: 'Roth IRA' },
  { value: 'traditional_ira', label: 'Traditional IRA' },
  { value: 'hsa', label: 'HSA' },
  { value: 'plan529', label: '529 plan' },
  { value: 'mortgage', label: 'Mortgage' },
  { value: 'loan', label: 'Loan (car, student, personal)' },
  { value: 'property', label: 'Property' },
  { value: 'vehicle', label: 'Vehicle (car, truck, boat)' },
  { value: 'business_checking', label: 'Business checking' },
  { value: 'business_credit', label: 'Business credit card' },
];
export const typeLabel = (t: AccountType) => TYPE_OPTIONS.find((o) => o.value === t)?.label ?? 'Not set yet';

/** A bank's account can't be a vehicle: one is entered by hand (investment views spec). Banks' type picker uses this. */
export const BANK_TYPE_OPTIONS = TYPE_OPTIONS.filter((o) => o.value !== 'vehicle');

const HOUSEHOLD_OWNERS: OwnerOption[] = [
  { key: 'jr', label: PERSON_1 }, { key: 'spouse', label: PERSON_2 }, { key: 'joint', label: PERSON_JOINT }, { key: 'business', label: BUSINESS },
];

/** The open book's owners (spec 2.1), as the server labels them; outside a book, the household's four. `keep` is the
 *  owner an account already has: when the book no longer offers it (a household of one, spec 2026-11-05 section 7),
 *  it stays in the list, so the picker shows it and a save never moves the account. */
export function ownerOptions(owners: OwnerOption[] | undefined, keep?: Owner): { value: Owner; label: string }[] {
  const list = (owners && owners.length ? owners : HOUSEHOLD_OWNERS).map((o) => ({ value: o.key, label: o.label }));
  if (keep && !list.some((o) => o.value === keep)) {
    list.push({ value: keep, label: HOUSEHOLD_OWNERS.find((o) => o.key === keep)?.label ?? keep });
  }
  return list;
}

/** Joint when the book has it, else its first owner (the server's default for a new bank account). */
export function defaultOwner(owners: OwnerOption[] | undefined): Owner {
  const list = ownerOptions(owners);
  return list.some((o) => o.value === 'joint') ? 'joint' : list[0].value;
}
