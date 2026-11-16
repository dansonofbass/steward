// The investment account page's words (investment views spec), loaded with its chunk. Its head's are in lib/copy.ts.

// What the bank sends
export const SENDS = '{institution} sends: {parts}';
export const SENDS_BALANCE = 'balance';
export const SENDS_TRANSACTIONS = 'transactions';
export const SENDS_NO_TRANSACTIONS = 'no transactions';
export const SENDS_HOLDINGS = 'holdings';
export const SENDS_NO_HOLDINGS = 'no holdings';

// This year
export const FIGURES_LABEL = 'This year at a glance';
export const THIS_YEAR = 'This year';
export const YOU_PUT_IN = 'You put in';
export const MARKET_GROWTH = 'Market growth';
export const SINCE_JAN1 = 'Since Jan 1';
export const SINCE_DAY = 'Since {date}';
export const NO_YEAR = 'No balance from this year yet.';
export const ESTIMATED = 'estimated from your pay facts';
export const FROM_PAY = 'from your pay facts';

// The chart
export const SINCE_WATCHING = 'Since {date} (when Steward started watching)';
export const NOT_ENOUGH_HISTORY = 'Not enough history yet.';
export const BALANCE_KEY = 'Balance';
export const CHART_LABEL = 'Balance from {from} in {since} to {to} now, with {in} put in.';

// What it's invested in, and what it costs
export const INVESTED_IN = "What it's invested in";
export const CLASS_LABELS = { us_stock: 'US stocks', intl_stock: 'International', bond: 'Bonds', cash: 'Cash', other: 'Other' } as const;
export const FUND = 'Fund';
export const VALUE = 'Value';
export const COST_A_YEAR = 'Cost a year';
export const COST_UNKNOWN = 'cost unknown';
export const ADD = 'Add';
export const RATIO_LABEL = 'Expense ratio for {symbol} (% a year)';
export const ALL_IN = 'All in, about **{amount} a year** ({pct}%).';
export const NOT_COUNTING_ONE = 'Not counting 1 fund with an unknown cost.';
export const NOT_COUNTING_N = 'Not counting {n} funds with an unknown cost.';
export const FROM_INSTITUTION = 'from {institution}, {date}';
export const FROM_STATEMENT = 'from Statement, {month} (PDF)';
export const FROM_IMPORT = "from {file}'s import, {date}";
export const IMPORT_PROMPT = "Import {institution}'s positions (CSV) to see what it's invested in and what it costs.";
export const IMPORT_POSITIONS = 'Import positions';
export const IMPORT_UNAVAILABLE = "Import positions couldn't load. Reload the page to try again.";
export const ADVISORY_LINE = 'Advisory fee {pct}%: about {amount} a year.';
export const ADVISORY_NONE = 'No advisory fee set.';
export const SET = 'Set';
export const CHANGE = 'Change';
export const FEE_LABEL = 'Advisory fee (% a year)';
export const FEE_HINT = "Leave it empty if there's none.";
export const FEE_RULE = 'Enter a fee between 0% and 3%.';

// Import positions
export const CHOOSE_FILE = 'Positions file (CSV)';
export const FIELD_LABELS = { symbol: 'Symbol', name: 'Name', shares: 'Shares', value: 'Value', cost_basis: 'Cost basis (optional)' } as const;
export const NOT_IN_FILE = 'Not in this file';
export const POSITION_ONE = '1 position';
export const POSITIONS_N = '{n} positions';
export const PREVIEW_SAME = '{positions} · {total}; your balance is {balance}';
export const PREVIEW_DIFF = '{positions} · {total}; your balance is {balance}, a difference of {difference}.';
export const PREVIEW_NO_BALANCE = '{positions} · {total}';

// Contributions and limits
export const CONTRIBUTIONS_TITLE = 'Contributions this year';
export const YOUR_CONTRIBUTIONS = 'Your contributions';
export const EMPLOYER_MATCH = 'Employer match';
export const ROLLOVERS_IN = 'Rollovers in';
export const NOT_COUNTED = 'Not counted toward the limit.';
export const LIMIT_LINE = '{in} of {limit} ({year} limit)';
export const MISSING = "This year's limits aren't in Steward yet.";
export const MAXED = 'Maxed for {year}.';
export const ON_PACE_TO_MAX = 'On pace to max it by Dec 31.';
export const ON_PACE_SHORT = 'On pace for {pace} by Dec 31: {short} short of the limit.';
export const RAISE = 'Raising your contribution {n}% for the rest of the year would max it.';
export const LIMITS_TITLE = 'Contribution limits for {year}';
export const ROW_LABEL = '{label} · {name}';

// The cheers (spec, Joy): copy, so they show whether celebrations are on or off.
export const MAXED_CHEER = 'Maxed your {kind} for {year}.';
export const FIRST_IMPORT_CHEER = "Now you can see what it's made of.";
