// The net worth split's words (investment views spec, Net worth), loaded with its chunk on Accounts.
import { GROUP_NOT_SET } from '../../lib/copy';

export const NET_WORTH = 'Net worth';
export const UP_THIS_YEAR = 'Up {amount} this year';
export const DOWN_THIS_YEAR = 'Down {amount} this year';
export const LINE_LABELS = {
  investable: 'Investable', home_and_cars: 'Home and cars', owed: 'What you owe', business: 'Business', unset: GROUP_NOT_SET,
} as const;
export const VEHICLE_LINE = '{name} · {loan}';
// The cheer (spec, Joy): copy, so it shows whether celebrations are on or off.
export const MILESTONE_CHEER = 'Net worth just crossed {amount}. Look at that.';
