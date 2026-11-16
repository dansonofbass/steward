// The Care screen's words (spec 4 and 10). Plain labels; a parent is called by name, never by a pronoun or an age word.
import type { Level } from './api';

export const fill = (text: string, values: Record<string, string>) => text.replace(/\{(\w+)\}/g, (_, k: string) => values[k] ?? '');

export const CARE = 'Care';
export const FOR = 'For {name}, {age}';
export const SET_UP_TITLE = 'Set up Care';
export const SET_UP_WHY = 'Care shows how long the money lasts with different kinds of care.';
export const WHO = "Who it's for";
export const BORN = 'Year born';
export const SPOUSE_BORN = "Spouse's year born";
export const SPOUSE_HINT = 'Leave blank if single or widowed.';
export const STATE = 'State';
export const SPENDING = 'Monthly spending';
export const SPENDING_HINT = 'Leave blank to use the transactions.';
export const GROWTH = 'Care costs rise, % a year';
export const GROWTH_RULE = 'Enter how fast care costs rise as a number, like 4.';
export const A_MONTH = 'a month';
export const NOT_SET_UP = "Care isn't set up yet. A manager can set it up.";
export const CHANGE_SETUP = 'Change setup';
export const SCENARIOS = 'Scenarios';
export const NO_SPENDING = 'No spending is counted yet, so every scenario lasts longer than it would. Add spending under Setup.';
export const ADD = 'Add a scenario';
export const MAX = 'Care compares up to {n} scenarios.';
export const CHANGE = 'Change';
export const REMOVE = 'Remove';
export const REMOVE_ASK = 'Remove {label}?';
export const REMOVE_NAMED = 'Remove {label}';
export const SCENARIO_REMOVED = 'Removed {label}.';
export const KEEP = 'Keep';
export const CARE_COST = "{cost} a month for care, in today's dollars";
export const YEAR_BY_YEAR = 'Year by year';
export const COLS = { year: 'Year (age)', balance: 'Savings', care: 'Care', ltc: 'Insurance pays', tax: 'Tax', mediCal: 'Medi-Cal' };
export const SHORT = 'Short {amount}';
export const MEDI_WORDS: Record<'eligible' | 'over_limit' | 'after_spend_down', string> = {
  eligible: 'Eligible', over_limit: 'Over by {amount}', after_spend_down: 'Spend down {amount}',
};
export const CHART_LABEL = 'Savings from {from} in {start} to {to} in {end}.';
export const CHART_OUT = ' Runs out in {year}.';
export const LEGEND_SAVINGS = 'Savings';
export const LEGEND_OUT = 'Runs out in {year}';
export const LEGEND_MC = 'Meets the Medi-Cal limit in {year}';
export const MEDI_CAL = 'Medi-Cal';
export const READ_RULE = 'Read the rule';
export const TOPICS = 'To ask an elder-law attorney about';
export const COSTS = 'Care costs';
export const ENTER_QUOTE = 'Enter a quote';
export const CHANGE_QUOTE = 'Change quote';
export const QUOTE_FOR = '{action} for {label}';
export const USE_TYPICAL = 'Use the typical figure';
export const USE_TYPICAL_ASK = 'Remove your quote and use the typical figure?';
export const REMOVE_QUOTE = 'Remove your quote for {label}';
export const QUOTE_REMOVED = 'Removed your quote for {label}. Care uses the typical figure.';
export const HOW = 'How this works';
// The scenario and quote sheets (Task 11)
export const ADD_TITLE = 'Add a scenario';
export const CHANGE_TITLE = 'Change this scenario';
export const KIND = 'Kind of care';
export const LEVELS: Record<Level, string> = {
  at_home: 'At home as today', in_home_help: 'In-home help', assisted_living: 'Assisted living', memory_care: 'Memory care',
  nursing_home: 'Nursing home',
};
export const STARTS = 'Starts';
export const NOW = 'Now';
export const HOURS = 'Hours a week';
export const DAYS = 'Adult day, days a week';
export const ROOM = 'Room';
export const ROOMS = { shared: 'Shared', private: 'Private' };
export const SELL = 'Sell the home';
export const SELL_YEAR = 'Year sold';
export const PRICE = 'Expected price';
export const PRICE_HINT = "Leave blank to use {value}, the home's value in the inventory.";
export const BASIS = 'What was paid, plus improvements';
export const BASIS_HINT = 'Leave blank to count the whole price over the exclusion as gain.';
export const SELLING = 'Selling costs, %';
export const SELLING_RULE = 'Enter selling costs as a number, like 6.';
export const FAMILY = 'Family adds each month';
export const CHANGE_SPENDING = 'Spending change each month';
export const CHANGE_HINT = 'Use a minus sign for less. Assisted living and nursing homes include rent and meals.';
export const QUOTE_TITLE = 'Quote for {label}';
export const QUOTE_AMOUNT = 'Amount';
export const QUOTE_DATE = 'Date of the quote';
export const PER = { hour: 'an hour', day: 'a day', month: 'a month' };
// Month by month (Task 12)
export const MONTH_BY_MONTH = 'Month by month';
export const NEXT_60 = 'Next 60 days';
export const NOTHING_EXPECTED = 'Nothing regular is expected in the next 60 days.';
export const COMING = 'Coming in {in} · Going out {out}';
export const ABOVE_FLOOR = 'Cash above the low-balance floors: {cash}';
export const CASH_ON_HAND = 'Cash on hand: {cash}';
export const RECENT = 'Recent months';
export const SO_FAR = ' so far';
export const IN_OUT = 'In {in} · Out {out}';
