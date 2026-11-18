// Profile's words (profile spec, the copy tables), in the Profile chunk. {placeholders} are filled by the caller.
// JR's rule (decision 6): no text the control already says. Server errors are shown as sent.
import type { SectionKey } from '../../lib/profileSections';

// The Profile frame
export const TITLE = 'Profile';
export const METER = '{n} of 5 done';
export const WHY: Record<SectionKey, string> = {
  you: 'Birthdays set your retirement and Social Security ages. Pay sets what you save.',
  kids: 'College is often the biggest cost before retirement.',
  home: "Counts in net worth. The Plan frees the mortgage payment once it's paid off.",
  benefits: 'Your income after work, and what health insurance costs before and after 65.',
  banks: 'Linked banks bring in balances and spending each day. Accounts kept by hand are updated by you.',
};
export const MINUTES = 'About {n} minutes';
export const START = 'Start';
export const CONTINUE = 'Continue';
export const SKIPPED = 'Skipped';
export const FIRST_VISIT = 'Everything you enter stays on your home server.';
// Issue #30: Home sends an unseen, unfinished profile here once a session; this says why.
export const OPENED_FROM_HOME = "Steward opened your profile in place of Home because it isn't finished.";
export const GO_HOME = 'Go to Home';
export const NEXT = 'Next';
export const DONE = 'Done';
export const SKIP = 'Skip';
export const BACK = 'Back';
export const SAVED = 'Saved';
export const STILL_NEEDED = 'Still needed: {what}';
// Plan-owned: the StepBar's name, the way back from a flow opened from the Plan, and four control names.
export const STEP_N_OF = 'Step {n} of {m}';
export const PLAN = 'Plan';
export const DISMISS = 'Dismiss';
export const EDIT = 'Edit';
export const CONFIRM = 'Confirm';
export const NOT_SET = 'Not set';
export const SAVED_BY = 'Saved {date} by {name}';   // the card's "Saved Oct 14 by JR" (spec, The card)

// You and your partner
export const STEP_YOU = 'You';
export const STEP_TAXES = 'Taxes';
export const STEP_PAY = 'Pay';
export const ONLY_THEY = 'Only {name} can change this.';
export const PAY_WHY = 'Bank deposits show pay after tax and 401(k), so Steward needs the figures from a pay stub.';
export const MATCH_ADDS = 'The employer adds {amount} a year.';
export const ROTH_HINT = "Enter 0 if there's no Roth 401(k).";
export const CARD_YOU = '{jr} and {spouse} · {state} · {filing}';
export const CARD_PAY = '{salary} a year · {pct}% to the 401(k)';

// Kids and college
export const STEP_KIDS = 'Kids';
export const STEP_COVER = 'What you plan to cover';
export const STEP_PLANS = '529s';
export const KID_NAME = 'Name';
export const BIRTH_YEAR = 'Birth year';
export const SCHOOL = 'School';
export const YOUR_SHARE = 'Your share';
export const LIVING = 'Living costs';
export const THEIR_529 = 'Their 529';
export const MONTHLY = 'Monthly contribution';
export const ADD_KID = 'Add a kid';
export const REMOVE = 'Remove';
export const REMOVE_NAMED = 'Remove {name}';   // the button's name says what goes (THO-12)
export const NO_KIDS = 'No kids';
export const ADDED = 'Added {name}';               // the toast adds "· Undo"
export const REMOVED = 'Removed {name}';           // the toast adds "· Undo"
export const COLLEGE_FROM = '{name} · college from {year}';
export const SCHOOL_ORDER = ['two_year', 'in_state_public', 'out_of_state_public', 'private', 'not_sure'] as const;
export const SCHOOLS: Record<(typeof SCHOOL_ORDER)[number], string> = {
  two_year: 'Trade or community college (2 years)', in_state_public: 'In-state public (4 years)',
  out_of_state_public: 'Out-of-state public (4 years)', private: 'Private (4 years)', not_sure: 'Not sure yet',
};
export const NOT_SURE_NOTE = 'Counted as in-state public.';
export const LIVING_IN = "We'll cover living costs";
export const LIVING_OUT = 'Tuition and fees only';
export const LIVING_WORD = { in: 'with living costs', out: 'tuition and fees only' } as const;
export const CONSEQUENCE = "About {total} in today's dollars for {years} years.";
export const CONSEQUENCE_ONE = "About {total} in today's dollars for 1 year.";   // plan-owned: "1 years" isn't English
export const CONSEQUENCE_529 = "{name}'s 529 is on track to cover about {covered}.";
export const CONSEQUENCE_ALL = "{name}'s 529 is on track to cover all of it.";
export const CONSEQUENCE_ZERO = 'Nothing for the Plan to set aside for {name}.';
export const PAST_AGE = '{name} is past college age.';
export const SUGGEST = "{account} looks like {name}'s.";
export const SUGGEST_OTHER = "{account} looks like {name}'s. It's set up as {type}.";
export const LINK_IT = 'Link it';
export const LINK_AND_TYPE = 'Link it and make it a 529 plan';
export const MONTHLY_SOURCE = 'From the last 12 months of deposits.';
export const UNLINKED = "{account} isn't linked to a kid, so the Plan waits.";
export const NO_529 = 'No 529';
export const KID_NAME_NEEDED = "Enter the kid's name.";
export const KID_YEAR_RANGE = 'Enter a birth year between {lo} and {hi}.';
export const KID_CARD = '{name} · born {year}';
export const KID_CARD_SUB = '{school} · {share}% · {living} · {plan}';

// Home and cars
export const STEP_OWN = 'Your home';
export const STEP_HOMES = 'Homes';
export const STEP_MORTGAGES = 'Mortgages';
export const STEP_CARS = 'Cars';
export const OWN = 'Do you own a home?';
export const YES = 'Yes';
export const NO = 'No';
export const OPEN_MORTGAGE = '{mortgage} is still open. Close it in Accounts, or choose Yes.';
export const VALUE = 'What it would sell for today';
export const ADD_PROPERTY = 'Add a property';
export const ADD_CAR = 'Add a car';
export const ADD_LOAN = 'Add a loan';
export const ADD_MORTGAGE = 'Add a mortgage';
export const WHERE_YOU_LIVE = 'Where you live';
export const MOVED_WHERE = 'Where you live is now {name}';   // the toast adds "· Undo"
export const LOAN_CHANGED = "Changed {name}'s loan";   // the toast adds "· Undo"
export const MORTGAGE_CHANGED = "Changed {name}'s mortgage";
export const PAYOFF_SET = 'Payoff date set';
export const WHERE_NOTE = 'The Plan and Care use where you live.';
export const NO_MORTGAGE = 'No mortgage';
export const NO_LOAN = 'No loan';
export const PAYMENT_SOURCE = 'From your {date} transfer to {mortgage}.';
export const PAYMENT_VARIED = 'It varied from {lo} to {hi}.';
export const PAYMENT_HINT = "Principal and interest only. Property tax and insurance don't end with the mortgage.";
export const OTHER_PROPERTY = 'Its payments stay in your spending in the Plan.';
export const ANY_CARS = 'Any cars?';
export const CAR_PLACEHOLDER = 'Subaru Outback';
export const KBB = 'Look it up on Kelley Blue Book';
export const KBB_NOTE = "Opens Kelley Blue Book in your browser. Steward doesn't look up the value.";
export const KBB_URL = 'https://www.kbb.com/whats-my-car-worth/';
export const BALANCE_FROM = 'From {bank}, {date}';      // spec, Step 3: "Read from the account as today"
export const CARD_WHERE = 'Where you live: {name} · {value}';
// {mortgage} · {rate}% · {payment} a month · paid off by {month}: each part appears only when it is known
export const CARD_RATE = '{rate}%';
export const CARD_PAYMENT = '{payment} a month';
export const CARD_PAYOFF = 'paid off by {month}';
export const CARD_THING = '{name} · {value}';
export const CARD_LOAN = '{loan} {balance}';
export const MORTGAGE_NAME = 'Mortgage';               // a mortgage added here (today's MORTGAGE_ACCOUNT_NAME)
export const LOAN_NAME = 'Loan';
export const LOAN_BALANCE = 'Balance';
export const HOME_NAME_DEFAULT = 'Home';
export const VALUE_CAR = 'What it would sell for';   // spec, Step 4
export const VALUE_CAR_NEEDED = 'Enter what it would sell for.';   // plan-owned, as VALUE_NEEDED is for a home
// Social Security and Medicare
export const STEP_SS = 'Social Security';
export const STEP_HEALTH = 'Health insurance and Medicare';
export const SS_WHY = 'Your benefit is set by your earnings in every year you worked. The Plan counts it from the age you claim.';
export const ADD_RECORD = 'Add earnings record';
export const USE_ESTIMATE = "Use Steward's estimate";
export const ESTIMATE_KEPT = 'Saved the estimate: {amount} a year';
export const RECORD_ADDED = 'Added the earnings record for {name}';
export const ESTIMATE_USED = "Using Steward's estimate for {name}";
export const SSA_STEPS = ['Sign in at ssa.gov/myaccount.', 'Open your Social Security Statement and choose Download your earnings record (an XML file).', 'Choose that file below.'];
export const RECORD_LINE = "{n} years, {first} to {last}. About {amount} a month at 67, in today's dollars.";
export const ESTIMATE_LINE = "Estimated from {jr}'s salary: about {amount} a month at 67, in today's dollars.";
export const SPOUSAL_LINE = 'Without a record, {partner} gets the spousal benefit: about {amount} a month at 67.';
export const PRIVACY = 'Steward keeps only the years and amounts. It discards your name and all other details and does not keep the file.';
export const HEALTH_WHY = 'Between retirement and 65 you buy your own health insurance. From 65, Medicare Part B is {part_b} a month each ({year}).';
export const ESTIMATE_SOURCE = "Steward's estimate: a typical Covered California Silver plan for your household, before subsidies.";
export const ABOUT_MONTHLY = 'About {amount} a month.';
export const CARD_RECORD = '{name}: record, {first} to {last} · about {amount} a month at 67';
export const CARD_ESTIMATE = "{name}: Steward's estimate · about {amount} a month at 67";
export const CARD_HEALTH = 'Health insurance: {premium} a year until 65';
// Banks and accounts
export const STEP_LINK = 'Link your banks';
export const STEP_TYPES = 'Account types';
export const STEP_HISTORY = 'Older history';
export const UNTYPED_WHY = 'Accounts without a type are left out of spending and the Plan.';
export const KEPT_BY_HAND = 'Kept by hand';
export const KEPT_WHY = "These don't update themselves. Update a balance from its account; the Plan notes any older than 90 days.";
export const MANAGE = 'Manage banks';
// Moments (P28)
export const CHEER_KIDS = 'College, planned.';
export const CHEER_HOME = 'Home sorted.';
export const CHEER_ALL = 'Your profile is complete. The Plan knows your household now.';

// Today's words, kept (from Set up Steward)
export const EARLIER_VALUES = 'Earlier values';
export const NO_EARLIER = 'No earlier values.';
export type Filing = 'mfj' | 'mfs' | 'hoh' | 'single';
export const FILING_ORDER: Filing[] = ['mfj', 'mfs', 'hoh', 'single'];
export const FILING_NAME: Record<Filing, string> = {
  mfj: 'Married filing jointly', mfs: 'Married filing separately', hoh: 'Head of household', single: 'Single',
};
export const YOUR_NAME = 'Your name in Steward';
export const YOUR_NAME_HINT = 'Both of you see this name.';
export const THEIR_NAME = "{name}'s name in Steward";
export const YOUR_BIRTHDAY = 'Your birthday';
export const THEIR_BIRTHDAY = "{name}'s birthday";
export const STATE = 'State';
export const CHOOSE_STATE = 'Choose a state';
export const FILING = 'Filing status';
export const NAME_NEEDED = 'Enter a name of up to 80 characters.';
export const BIRTHDAY_NEEDED = 'Enter a birthday.';
export const BIRTHDAY_PAST = 'Enter a birthday in the past.';
export const STATE_NEEDED = 'Choose a state.';
export const FILING_NEEDED = 'Choose how you file taxes.';
export const IMPORT_LINE = 'Import a file from your bank';
export const IMPORT_SUB = 'CSV, OFX or QFX. Rows already in Steward are found and skipped.';
export const HOME_VALUE = 'Home value';
export const REDFIN = 'Look it up on Redfin';
export const REDFIN_URL = 'https://www.redfin.com/';
export const REDFIN_NOTE = 'Opens Redfin in your browser. Steward does not store your address or look up the value itself.';
export const RATE = 'Interest rate';
export const RATE_PLACEHOLDER = 'e.g. 3.25';
export const PAYMENT = 'Monthly payment';
export const PAID_OFF_BY = 'Paid off by';
export const PAID_OFF_NOW = 'Paid off';
export const CALC_HOW_ONE = 'Calculated from the balance, rate and payment: 1 more payment.';
export const CALC_HOW = 'Calculated from the balance, rate and payment: {n} more payments.';
export const CALC_WAITING = 'Enter the balance, rate and payment to work out the payoff date.';
export const ENTER_DATE = 'Enter a different date';
export const USE_CALC = 'Use the calculated date';
export const OVERRIDE_HOW = 'Calculated date: {date}. The Plan uses the date you enter.';
export const OVERRIDE_ONLY = 'The Plan uses the date you enter.';
export const NEVER_PAID = 'At this rate and payment the balance never goes down. Check the payment, or enter a date.';
export const VALUE_NEEDED = 'Enter what the home would sell for today.';
export const BALANCE_NEEDED = 'Enter the balance from your latest statement.';
export const RATE_NEEDED = 'Enter the interest rate, like 3.25.';
export const RATE_FORMAT = 'Use at most three decimals, like 2.875.';
export const PAYMENT_NEEDED = 'Enter the monthly payment.';
export const PAYOFF_NEEDED = 'Choose the month the mortgage is paid off.';
export const PERCENT_RANGE = 'Enter a percentage between 0 and 100.';
export const PAY_SALARY = "{jr}'s yearly salary, before deductions";
export const PAY_K401 = '401(k) contribution';
export const PAY_ROTH = 'Roth share of the contribution';
export const MATCH_RATE = 'Match rate';
export const MATCH_CAP = 'Match cap';
export const A_YEAR = 'a year';
export const A_MONTH = 'a month';
export const SALARY_NEEDED = "Enter {jr}'s yearly salary before deductions.";
export const HEALTH_PREMIUM = 'Yearly premium for the household';
export const PREMIUM_NEEDED = 'Enter the yearly premium.';
export const LABEL = 'Label';
export const CHOOSE_FILE_FOR = "Choose {who}'s earnings record file";
export const NOTHING_WAS_SAVED = 'Nothing was saved.';
export const SIMPLEFIN_LINKED = 'SimpleFIN linked';
export const SIMPLEFIN_NOT_LINKED = 'SimpleFIN not linked';
export const ACCOUNT_ONE = '1 account';
export const ACCOUNTS_N = '{n} accounts';
export const ALL_TYPED = 'all with a type';
export const SOME_UNTYPED = '{n} with no type yet';
