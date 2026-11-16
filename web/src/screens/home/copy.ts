import type { Phase } from '../../lib/sky';

// Home (phase 11 spec): Copy: Figure and Copy: Signs. The headline's strings are lib/copy.ts's H_*; For you's and
// Since's are added by their tasks.

// Phase 17 spec 3.7: a greeting word from the sky phase on the date line ("Monday, Nov 2 · good evening"). The night
// after midnight says "up late".
export const GREETING: Record<Phase, string> = {
  night: 'good evening', dawn: 'good morning', sunrise: 'good morning', morning: 'good morning',
  day: 'good day', afternoon: 'good afternoon', evening: 'good evening', dusk: 'good evening',
};
export const GREETING_LATE = 'up late';

export const FIG_BLACK = '{amount} in the black so far this month';
export const FIG_RED = '{amount} in the red so far this month';
export const FIG_EVEN = 'Even so far this month';
export const FIG_NOTHING = 'Nothing in or out yet this month.';
export const LEGEND_IN = '{amount} in';
export const LEGEND_OUT = '{amount} out';
export const PAYDAY = "Payday's usually the {day}.";
export const JOY = 'Already your best month in a year.';

export const SIGN_FLEXIBLE = 'Flexible spending';
export const SIGN_BILLS = 'Bills';
export const SIGN_PLAN = 'Plan';
export const SIGN_NET_WORTH = 'Net worth';
export const SIGN_BUSINESS = 'Business';
export const FLEX_OF = '{spent} of {target}';
export const FLEX_SO_FAR = '{spent} so far';
export const BILLS_ALL_PAID = 'All paid';
export const BILLS_PAID_OF = '{paid} of {n} paid';
export const BILLS_REST_LATER = 'rest due later';
export const BILLS_NOT_SEEN = '{category} not seen yet';
export const BILLS_K_NOT_SEEN = '{k} not seen yet';
export const BILLS_NONE = 'None due';
export const PLAN_AT = 'Comfortably at {age}';
export const PLAN_NOT_BY_70 = 'Not by 70';
export const PLAN_NONE = 'No plan yet';
export const NW_THIS_MONTH = '{amount} this month';
export const NW_NO_CHANGE = 'No change yet';
export const BUSINESS_PROFIT = '{amount} profit this year';

// Copy: For you.
export const FOR_YOU = 'For you';
export const REVIEW_N = '{n} to sort in Review';
export const REVIEW_ONE = '1 to sort in Review';
export const OWES_YOU = '{payer} owes you {amount}';
export const OTHERS_OWE = '{n} others owe you {amount}';
export const OTHER_OWES = '1 other owes you {amount}';   // plan-owned (engineering choice 22): "1 others" doesn't read
export const SAME_ONE = 'Same account? {name} came in twice';
export const SAME_N = '{n} same-account questions';
export const UNTYPED_ONE = '1 new account needs a type';
export const UNTYPED_N = '{n} new accounts need a type';
export const ACT_REVIEW = 'Review ›';
export const ACT_IMPORT = 'Import ›';   // plan-owned (Engineering choice 14)
export const ACT_SEE = 'See ›';
export const ACT_FIX = 'Fix ›';
export const ACT_ANSWER = 'Answer ›';
export const ACT_SET = 'Set ›';
export const ACT_CONTINUE = 'Continue ›';
export const MORE_N = '{n} more';
export const DISMISSED = 'Dismissed';                     // the toast adds " · Undo"
export const NOTHING_NEEDS_YOU = 'Nothing needs you.';