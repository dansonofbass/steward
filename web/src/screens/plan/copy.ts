// Plan tab vocabulary (spec 6), in the Plan chunk. Strings with {placeholders} are filled by the caller.
import type { PlanLevel } from '../../api/household';

// Setup checklist
export const PLAN_TITLE = 'Plan';
// The one-sentence headline (roadmap 14). The odds are the Comfortably test: 9 of 10 simulated market histories.
export const HEADLINE = "Retire at {age}, with about {amount} a month for living costs in today's dollars.";
export const HEADLINE_ODDS = 'The plan also pays the mortgage until it ends, health insurance and big one-off costs. In 9 of 10 simulated market histories, the money lasts until {younger} is 95.';
export const HEADLINE_NONE = "Not by 70 with about {amount} a month for living costs in today's dollars.";
export const HEADLINE_NONE_NEXT = 'Try changes shows what brings it closer.';
export const PLAN_PAGES = 'Plan pages';
// The five pages (plan subpages decision 1)
export const OVERVIEW = 'Overview';
export const TRY_CHANGES = 'Try changes';
export const HOW_IT_WORKS = 'How it works';
export const TAXES_TAB = 'Taxes';
// Try changes' pinned bar (plan subpages): the headline's amount and odds, compact.
export const TRYBAR_AMOUNT = "{amount} a month in today's dollars";
export const TRYBAR_ODDS = 'the money lasts in 9 of 10 market histories';

// The Overview's two cards (plan subpages decision 2)
export const HELP_MOST = 'What would help most';
export const HELP_MOST_LINK = 'See them in Try changes';
export const NOTHING_HELPS = 'Nothing on the list brings it earlier right now.';
export const NEXT_DOLLAR_CARD = 'Your next dollar';
export const NEXT_STEP_LINK = 'See every step in Next dollar';
export const REQUIRED = 'Required';
export const SETUP_LEDE = 'To work out when you can retire, Steward needs some information that is not in your accounts.';
export const SETUP_NOTE = 'Each item takes a minute or two. The plan shows no ages until every required item is done.';
export const SETUP_NOTE_VIEWER = 'A manager of this book fills these in. The plan shows no ages until every required item is done.';
export const N_OF_M_DONE = '{n} of {m} done';
export const OPTIONAL = 'Optional';
export const STAYS_HOME = 'Everything you enter is stored on your home server and is not sent anywhere else.';
export const HEALTH_PREFILLED = 'An estimate is filled in for you to check.';
export const AUTOMATIC = 'Automatic';
export const GO_DONE = 'Done';
export const STATUS_TO_DO = 'To do';
export const GO_ADD = 'Add';
export const GO_UPLOAD = 'Upload';
export const GO_FINISH = 'Finish';
export const GO_CHECK = 'Check';
export const GO_IMPORT = 'Import';

// The two ages
export const COMFORTABLY_AT = 'Comfortably at';
export const LIKELY_AT = 'Likely at';
export const IN_YEAR = 'in {year}';
export const WAS = 'was {age}';
export const NOT_BY_70 = 'Not by 70';
export const COMFORTABLY_NOT_BY_70 = 'Comfortably: not by 70';
export const LIKELY_NOT_BY_70 = 'Likely: not by 70';
export const SAVED_ON = 'on {date}';
export const TIP_COMFORTABLY = 'In 9 of 10 simulated market histories, the money lasts until {younger} is 95.';
export const TIP_LIKELY = 'In 8 of 10 simulated market histories, the money lasts until {younger} is 95.';
export const YOUNGER_OF_YOU = 'the younger of you';
export const PLAN_SAVED_BY = 'Plan saved by {name} {when}';
export const NOT_SAVED_YET = 'Not saved yet';
export const EARLIER_VERSIONS = 'Earlier versions';
export const FROM_SAVED = 'From the plan saved {date}';
export const SOMEONE = 'someone';

// Levers
export const WHAT_WOULD_CHANGE_IT = 'What would change it';
export const LEVERS_TIP = 'Each row changes one thing and keeps the rest of the plan the same. Open a row and drag its slider to see the new ages.';
export const LEVERS_INTRO = 'Sorted by the effect on the Comfortably age, largest first.';
export const TRY_THIS = 'Try this';
export const CHANGE_SUGGESTION = 'Change suggestion';
export const SUGGESTION = 'Suggestion';
export const DONE = 'Done';
export const SAVED_PLAN_VALUE = 'Saved plan: {value}';
export const SAVED_PLAN_MARK = 'Saved plan';
export const IN_USE = 'In use';
export const NO_HISTORY_YET = 'No history yet';
export const NO_HISTORY_FOOT = 'No history yet, so the suggestion is the smallest step.';
export const CHANGED = 'Changed';
export const WORKING_IT_OUT = 'Working it out…';
export const YOU_SET_THIS_SUGGESTION = 'You set this suggestion.';
export const USE_LAST_YEAR = "Use last year's amount";
export const CUT_FROM_2034 = 'Cut from 2034';
export const NO_CUT = 'No cut';
export const FULL_SS_NOTE = 'The plan includes the benefit cut the Social Security trustees expect from 2034, unless you choose No cut.';
export const LEVEL_A_YEAR = '{level} · about {cost} a year';
export const KID_SHARE_LINE = '{share}%, {living}.';
export const CHANGE_IN_PROFILE = 'Change in Profile';
export const LIVING_WORD = { in: 'with living costs', out: 'tuition and fees only' } as const;

// Save bar
export const PLAN_NOT_UPDATED = 'Plan not updated';
export const FIRST_SAVE = 'No plan is saved yet. Save one to show these ages on Home.';
export const SAVE_THE_PLAN = 'Save the plan';
export const RESET = 'Reset';
export const UPDATE_THE_PLAN = 'Update the plan';
export const PLAN_UPDATED = 'Plan updated.';
export const CURRENT_TAG = 'Current';

// Band chart
export const BAND_TITLE = 'Money for retirement, year by year';
export const TYPICAL_MARKETS = 'Typical markets';
export const ROUGH_TO_GOOD = 'Rough to good markets';
export const RETIRE_AT = 'Retire at {age}';
export const GOOD = 'Good';
export const TYPICAL = 'Typical';
export const ROUGH = 'Rough';
export const BAND_CAPTION = "In today's dollars. Includes cash, investments and retirement accounts. Does not include the house.";
export const NO_BAND = "Not by 70 at today's settings, so there's no retirement year to chart yet. The levers on Try changes show what would get there.";

// Next dollar (cash-flow and tax spec section 6)
export const NEXT_DOLLAR_TITLE = 'Next dollar';
export const ND_DONE = 'Done';
export const ND_TO_DO = 'To do';
export const ND_LATER = 'Later';
export const ND_ASK = 'Question';
export const ND_NO_ROOM = 'No room';
export const ND_CANT_TELL = "Can't tell";
export const CASH_NOW = 'Cash now';
export const STILL_TO_ADD = 'Still to add';
export const IN_THIS_YEAR = 'In this year';
export const ROOM_LEFT = 'Room left';
export const ROOM_LEFT_RULES = 'Room left ({year} limits)';
export const MORE_A_YEAR = 'More a year';
export const OWED = 'Owed';
export const HSA_YES = 'Yes';
export const HSA_NO = 'No';
export const HSA_UNSURE = 'Not sure';
export const RATE_FOR = '{name} rate (%)';
export const RATE_RANGE = 'Enter a rate from 0 to 100.';
export const PAYROLL_LABEL = 'Put in through payroll this year';
export const PAYROLL_BLANK = "Add what your paycheck puts in to see what's left.";
export const PAYROLL_RANGE = 'Enter an amount from $0 to $100,000.';
export const ND_SAVE = 'Save';
export const ND_SETTINGS_LINE = 'Cash target: {months} months of spending. Debt rate: above {rate}.';
export const ND_CHANGE = 'Change';
export const ND_SETTINGS_TITLE = 'Next dollar settings';
export const CASH_MONTHS_LABEL = 'Months of spending to keep in cash';
export const CASH_MONTHS_RANGE = 'Enter whole months from 1 to 24.';
export const DEBT_RATE_LABEL = 'Pay down debt above this rate (%)';
export const SUGGESTS_ONLY = 'Steward suggests; it never moves money.';
export const ROTH_LINK = 'If your income is too high for a Roth';
export const ROTH_SHEET_TITLE = 'A Roth when income is too high';

// How this works
// How it works, opened out (plan subpages decision 5): today's words under three headings, nothing new.
export const HOW_MOVES = 'What moves your plan most';
export const MOVES_SS = 'Social Security at 67';
export const MOVES_SPENDING = 'Spending in retirement';
export const MOVES_MORTGAGE = 'Mortgage paid off';
export const MOVES_HEALTH = 'Health before Medicare';
export const MOVES_COLLEGE = 'College';
export const MOVES_SAVING = 'Saving now';
export const MOVES_A_MONTH = '{amount} a month';
export const MOVES_TWO = '{jr} {a} · {spouse} {b} a month';
export const MOVES_A_YEAR = '{amount} a year';
export const MOVES_KIDS = '{n} kids';
export const MOVES_KIDS_LEVEL = '{n} kids · {level}';
export const MOVES_KID_LEVEL = '1 kid · {level}';
export const MOVES_KID = '1 kid';                    // plan-owned: one kid whose level the server didn't send
export const CHANGE = 'Change';
export const CHANGE_NAMED = 'Change {label}';         // plan-owned: the link's name, so each Change says what it changes
/** plan-owned: short forms of lib/college's LEVEL_NAME for the College row ("3 kids · in-state"). */
export const COLLEGE_SHORT: Record<PlanLevel, string> = { two_year: 'trade or community college', in_state_public: 'in-state', out_of_state_public: 'out-of-state', private: 'private' };
export const FOLDS = { markets: 'Markets', taxes: 'Taxes', ss: 'Social Security rules', lifespans: 'Lifespans', costs: 'Costs and withdrawals' } as const;
export const HOW_SOURCES = 'Where your numbers come from';
export const HOW_AGES = 'What the ages mean';
export const HOW_HISTORIES = 'Steward runs your money through {n} simulated market histories built from real market returns since 1928.';
export const HOW_AGES_BODY = 'Comfortably is the first age at which the money lasts until {younger} is 95 in 9 of 10 histories. Likely is the first age at which it lasts in 8 of 10.';
export const LU_BALANCES = 'Account balances';
export const LU_PAY = 'Pay';
export const LU_EARNINGS = 'Earnings records';
export const LU_CHILDREN = 'Kids and college';
export const LU_MORTGAGE = 'Mortgage payment';
export const LU_HEALTH = 'Health insurance';
export const LU_SPENDING = 'Spending history';
export const NOT_ADDED = 'not added';
export const ACCOUNTS_LOADING = 'loading';
export const ACCOUNTS_UNAVAILABLE = 'not available';
export const CHILD_ONE = '1 child';
export const CHILDREN_COUNT = '{n} children';
export const MONTHS_COUNT = '{n} months';
export const LEFT_OUT_ONE = '1 new account has no type yet and is left out.';
export const LEFT_OUT_MANY = '{n} new accounts have no type yet and are left out.';

export { LEVEL_NAME, LEVELS } from '../../lib/college';

export const BAND_END_SPOUSE = '{age} · {spouse} 95';
export const BAND_LABEL = "Money for retirement by {name}'s age, from {first} to {last}, in today's dollars.";
export const BAND_START = '{name} {age}';
// The business range (business plan ruling 11)
export const PLAN_BUSINESS_RANGE = 'Business profit for {year}, before the home office and mileage: {low} to {high} expected. The Consulting income row tries the middle, {mid}.';
export const PLAN_BUSINESS_YTD = 'Business profit so far in {year}, before the home office and mileage: {ytd}. The Consulting income row tries that until you add what you expect for the rest of the year.';
export const PLAN_BUSINESS_ASK = 'Add what you expect to make in {year} on the Business page. Until then the Consulting income row tries only what came in so far, {ytd}.';
export const BUSINESS_PAGE = 'Business page';

// Big costs ahead (phase 11c)
export const BIG_COSTS = 'Big costs ahead';
export const BIG_COSTS_INTRO = 'The one-offs you are setting aside. The plan pays each in its year, from what has been put away first, then from savings.';
export const BIG_COST_SUB = '{month} · {monthly} a month until then';
export const BIG_COST_OVERDUE = 'Due {due}, now planned for {year}';
export const BIG_COSTS_NOTE = "Yearly costs like property tax and car insurance are already in the plan's spending history, so they are not listed here. Property tax counts there even though it sits under Taxes on Spending. Only the one-offs are listed, each paid in its year.";
export const SETTING_ASIDE_LINK = 'Setting aside';
export const ESTIMATE_TAG = 'Estimate';
export const YEARLY_BULLET = "Yearly costs you set aside, like property tax and car insurance, are already in the spending history and are not listed. Property tax counts there even though it sits under Taxes on Spending. Income tax is left out: the plan works that out itself.";
export const ONE_OFFS_BULLET = 'Big one-off costs you are setting aside are not part of your spending; each comes out in its year: {list}.';
export const ONE_OFF_BULLET = 'A big one-off cost you are setting aside is not part of your spending; it comes out in its year: {list}.';
export const ESTIMATE_WORD = '(estimate)';
export const LU_SET_ASIDES = 'Set-asides';
export const LU_SET_ASIDES_BY = '{date}, by {name} · {n}';
export const LU_SET_ASIDES_NO_NAME = '{date} · {n}';
export const ONE_OFFS_IN_PLAN = '{n} one-offs in the plan';
export const ONE_OFF_IN_PLAN = '1 one-off in the plan';
export const NO_ONE_OFFS = 'no one-offs in the plan';

// What changed since the last saved plan (plan subpages). The arrow is drawn beside the words, not in them.
export const CHANGE_UP = 'Up {span} since {date}';
export const CHANGE_DOWN = '{span} later than on {date}';
export const CHANGE_SAME = 'No change since {date}.';
export const CHANGE_NOW_ABLE = 'Comfortably at {age} now, from not by 70 on {date}';
export const CHANGE_NOT_NOW = 'Not by 70 now, from {age} on {date}';
export const SPAN_MONTH = '1 month';
export const SPAN_MONTHS = '{n} months';
export const SPAN_YEAR = '1 year';
export const SPAN_YEARS = '{n} years';
export const FACT_SPENDING_LOWER = 'spending is {amount} a month lower';
export const FACT_SPENDING_HIGHER = 'spending is {amount} a month higher';
export const FACT_RETIREMENT_GREW = 'retirement accounts grew {amount}';
export const FACT_RETIREMENT_FELL = 'retirement accounts fell {amount}';
export const FACT_SAVING_MORE = "you're saving {amount} a month more";
export const FACT_SAVING_LESS = "you're saving {amount} a month less";
export const FACT_SS_RECORD = 'Social Security is now from your record';
export const FACT_BIG_COST = 'a new big cost: {name} in {year}';
export const FACTS_AND = '{a} and {b}';
// The change line's cheers (plan subpages decision 7), drawn without repeats by lib/lines drawFrom. About time won
// back, warm, never about money spent.
export const CLOSER_CHEERS = {
  half: [
    'Half a year closer.',
    'Months closer, and it shows.',
    'A good stretch closer.',
    'Closer than last time, by a fair bit.',
    'Steady steps. They add up.',
    'That brought it nearer.',
  ],
  year: [
    'A year closer.',
    'A whole year sooner.',
    "One more year that's yours.",
    'A year back on your side.',
    'Twelve months nearer. Well earned.',
    'That moved it a full year.',
  ],
  years: [
    'Years closer!',
    'Years sooner. Take that in.',
    "Now that's a leap.",
    'Retirement just came a lot nearer.',
    'Years back on your side.',
    'What a change. Years closer.',
  ],
} as const;
