import type { Field } from './api';

export const HEADING = 'Import';
/** The narrowest a column of the confirm table gets, in rem: more columns than a phone fits scroll inside the table. */
export const COL_REM = 5.5;
export const DROP = 'Drop bank files here';
export const CHOOSE = 'Choose files';
export const FORMATS = 'CSV, OFX, QFX or PDF · 5 MB each, PDFs 15 MB · up to 30 files';
export const READING = 'Reading…';
export const READING_N = 'Reading {n} files…';
export const READING_ONE = 'Reading 1 file…';             // plan-owned singular
export const READ_N = '{n} files read';
export const READ_ONE = '1 file read';                    // plan-owned singular
export const TAG_KNOWN = '{label} · {n} rows';
export const TAG_OFX = 'OFX · {n} rows';
export const TAG_REMEMBERED = '{label} · remembered layout';
export const TAG_ASK_AGAIN = '{label} · 1 question';      // plan-owned: a remembered layout the evidence contradicts
export const TAG_NEW_ONE = 'New layout · 1 question';
export const TAG_NEW_N = 'New layout · {n} questions';
export const TAG_NEW_CHECK = 'New layout · check the columns';
export const TAG_NEW_DONE = '{label} · new layout';
export const NEW_LAYOUT = 'New layout';
export const TAG_BEFORE = ' · imported on {date}';
export const ACCOUNT_FOR = 'Account for {file}';
export const ACCOUNT_EMPTY = 'Choose an account';
export const NEW_ACCOUNT = 'New account…';
export const IN_INVENTORY = 'Add an account in Inventory';
export const REMOVE = 'Remove {file}';
export const REMOVED = 'Removed {file}';
export const PREVIEW = 'Preview';
export const TOO_MANY = 'A batch holds up to 30 files. Import these, then add the rest.';
export const TOO_BIG = 'Bigger than 5 MB. Download a shorter date range and try again.';
export const EXPIRED = 'These files expired. Add them again.';
export const ANSWER_FOR = 'Answer the question for {file}';

export const COLUMNS_IN = 'Columns in {file}';
export const COLUMN_N = 'Column {n}: {header}';
export const OPTIONS: readonly (readonly [Field | 'ignore', string])[] = [
  ['date', 'Date'], ['description', 'Description'], ['memo', 'Memo'], ['amount', 'Amount'], ['debit', 'Money out'],
  ['credit', 'Money in'], ['direction', 'Type'], ['status', 'Status'], ['id', 'Bank id'], ['ignore', 'Ignore'],
];
export const INVALID = 'Choose an amount column, or both a money-out and a money-in column.';
export const REMEMBERED_NOTE = 'Steward remembers this layout, so the next file like it asks nothing.';
export const USE = 'Use this layout';

export const CARD_LEAN = 'Purchases look {lean} in this file. Which way do the signs run?';
export const BANK_LEAN = 'Money out looks {lean} in this file. Which way do the signs run?';
export const NO_LEAN = 'Which way do the signs run in this file?';
export const CARD_OPTIONS = ['Purchases are positive', 'Purchases are negative'] as const;
export const BANK_OPTIONS = ['Money out is positive', 'Money out is negative'] as const;
export const SIGN_CHANGED = "This file's signs look the other way from last time.";
export const NO_ACCOUNT = 'Choose an account';
export const DATES_READ = 'Dates read as {reading}.';
export const DATE_QUESTION = 'Is {value} {a} or {b}?';

export const STEP_TWO = 'Preview';                        // plan-owned: step 2's heading, where focus lands
export const NEW = 'New transactions';
export const ALREADY = 'Already in Steward (skipped)';
export const SIMPLEFIN_AFTER = 'SimpleFIN already has these (after {date})';
export const SIMPLEFIN = 'SimpleFIN already has these';
export const SKIPPED = '{n} · skipped';
export const SAME = 'Looks the same, check';
export const LOOK = 'Look';
export const LOOK_ON = 'Look: {line}';
export const COVERS = 'Covers';
export const MORE_ERRORS = '{n} more';
export const IMPORT_N = 'Import {n}';
export const BACK = 'Back';
export const CHANGED = 'Something changed since the preview. Check the new numbers.';
export const LOOK_TITLES = { same: 'Looks the same', simplefin: 'SimpleFIN already has these', already: 'Already in Steward', balances: 'Balances', holdings: 'Holdings' } as const;
export const IN_FILE = 'In the file';
export const IN_STEWARD = 'In Steward';
export const EARLIER = 'Earlier in this file';
export const IMPORT_ANYWAY = 'Import anyway';
export const IMPORT_TOO = 'Import these too';
export const DONE = 'Done';
export const HAS_FROM = 'SimpleFIN has this account from {date}';
export const NOT_SHOWN = "{n} more aren't shown";
export const LEFT_OUT = {
  pending: ['1 pending row left out', '{n} pending rows left out'],
  balance: ['1 balance line left out', '{n} balance lines left out'],
  totals: ['1 totals row left out', '{n} totals rows left out'],
  currency: ['1 row in another currency left out', '{n} rows in another currency left out'],
} as const;                                               // the singulars are plan-owned

export const RESULT_N = 'Imported {n} into {k} accounts';
export const RESULT_ONE = 'Imported {n} into {account}';
export const UNDONE = 'Import undone.';
export const JOY = "That's {n} months of history in one go.";
export const PAST_BATCH = '{n} files · {rows} rows · {date}';
export const UNDO_SET_TITLE = 'Undo the import of {n} files?';      // plan-owned
export const UNDO_SET_BODY = 'Its {rows} rows from {n} files are removed from Steward for good, with any categories or notes added since. The accounts, your other imports and everything from the bank stay, and the log keeps a line saying it was undone.';
export const NOTHING_YET = 'Nothing imported yet.';
export const UNDONE_ON = 'Undone {date}';
export const REMOVED_ACCOUNT = 'Removed account';

export const LAYOUTS = 'Remembered layouts';
export const LAYOUT_ROW = '{label} · last used {date}';
export const LAYOUT_STATEMENT_ROW = '{label} · statement · last used {date}';
export const EDIT = 'Edit';
export const FORGET = 'Forget';
export const SAVE = 'Save';
export const LAYOUT_NAME = 'Name';
export const FORGOT = 'Forgot {label}';
export const NO_LAYOUTS = 'No layouts yet.';
export const DATE_CHOICES = { month: 'Month/day/year', day: 'Day/month/year' } as const;   // plan-owned radio labels

export const TOO_BIG_PDF = 'Bigger than 15 MB. Download it again or split it.';
export const ST_QUEUED = 'Waiting to be read';
export const ST_READING_NEW = 'New layout · reading on {gateway}…';
export const ST_WAITING = 'Waiting for {gateway}';
export const ST_NOT_PAIRED = 'Reading this needs {gateway}. Pair it in Settings › Chat.';
export const ST_NO_MODEL = 'Reading this needs a local model on {gateway}.';   // INS-12: paired, but no model pulled
export const ST_OLD_GATEWAY = '{gateway} needs an update to read new layouts.';
export const ST_OLD_GATEWAY_PDF = '{gateway} needs an update to read PDFs.';   // remote-reading P63
export const ST_CHECK_LAYOUT = 'Check the layout · 1 look';
export const ST_OFF = 'Off by {gap} · Check rows';
export const ST_CHECK_ROWS = 'Check rows';                                  // plan-owned: off, but no gap to say
export const ST_ANYWAY = 'Off by {gap} · importing anyway';
export const ST_CHECK_ROWS_ANYWAY = 'Check rows · importing anyway';        // plan-owned: off with no gap, imported anyway
export const ST_READY_ROWS = '{label} · {month} · {n} rows · adds up ✓';
export const ST_CHOOSE_ACCOUNT = 'Choose its account to check it';              // plan-owned: its account says bank or owed
export const ST_ADDED_BY = ' · Added by {name}';
export const ST_CLEARED = 'Cleared after a week · Add again';
export const PREVIEW_SOME = 'Preview {n} ready';
export const ST_JOY = '{n} statements, every one adds up.';
export const ST_ANNOUNCE = '{file}: {tag}';                                 // plan-owned: the polite line per change
export const BALANCES = 'Balances {n}';
export const BALANCES_KEPT = 'Balances {n} · {k} kept';
export const KEPT = 'kept';
export const KEPT_BALANCE = 'Balance for {date} already in Steward · kept';
export const PAST_PDF = '{account} · {month} (PDF) · {rows} rows';
export const PAST_OFF = "didn't add up";

export const LAYOUT_REGION = '{file}: check the layout';
export const REVIEW_REGION = '{file}: check rows';                                    // plan-owned, as the layout's
export const LAYOUT_CHECK = '{opening} {a} → {closing} {b} · adds up ✓';
export const LAYOUT_REMEMBERED = 'Steward remembers this layout.';
export const LOOKS_RIGHT = 'Looks right';
export const NOT_RIGHT = 'Not right';
export const ROWS_ONE = '1 row';                                                       // plan-owned singular
export const ROWS_N = '{n} rows';
export const REVIEW_OFF = 'Off by {gap}';
export const REVIEW_ADDS_UP = 'Adds up ✓';
export const REVIEW_SECTION = '{section} are off by {gap}';
export const REVIEW_COLUMNS = ['Date', 'Description', 'Amount', 'Page'] as const;
export const REVIEW_CELL = '{column}, row {n}';                                        // plan-owned, spec Accessibility
export const REVIEW_REMOVE = 'Remove row {n}';
export const REVIEW_REMOVED = 'Removed · Undo';
export const ADD_ROW = 'Add a row';
export const ROWS_CAPTION = 'Rows in {file}';                                          // plan-owned caption
export const UNREADABLE_LINE = 'Page {n}: {text}';                                     // plan-owned
export const ST_READING_SCAN = 'Scanned · reading on {gateway}, about 20 s a page · page {n} of {m}';
export const ST_TRY_AGAIN = 'Try again';
export const SCAN_NOTE = 'Descriptions read from a scan · check them';       // plan-owned (P25, Engineering choice 9)
export const SCAN_CELL = 'read from a scan';                                 // plan-owned, for screen readers per cell

export const ST_CHECK_HOLDINGS = 'Check the holdings · 1 look';
export const ST_READY_HOLDINGS = '{label} · {month} · {holdings} · adds up ✓';
export const HOLDINGS_ONE = '1 holding';                                                 // plan-owned singular
export const HOLDINGS_N = '{n} holdings';
export const ST_READY_LOAN = '{label} · {month} · balance {amount}';
export const HOLDINGS_ADD_UP = 'Holdings add up to the total ✓';
export const HOLDINGS_SHORT = 'Holdings are {gap} short of the total';
export const HOLDINGS_OVER = 'Holdings are {gap} over the total';
export const CHECK_HOLDINGS = 'Check holdings';                              // plan-owned: no holdings, or no total
export const ST_NOT_INVESTMENT = "{account} isn't an investment account. Holdings usually go on one.";   // plan-owned, never blocks
export const ST_NOT_LOAN = "{account} isn't a loan account. Loan statements usually go on one.";          // plan-owned, never blocks
export const ST_OLD_HOLDINGS = '{gateway} needs an update to read holdings.';     // plan-owned, as ST_OLD_GATEWAY
export const ENDING = 'Ending balance {amount} on {date}';
export const HOLDINGS_COLUMNS = ['Symbol', 'Name', 'Shares', 'Value'] as const;     // plan-owned
export const PV_HOLDINGS = 'Holdings {n} statements';
export const PV_HOLDINGS_ONE = 'Holdings 1 statement';                        // plan-owned singular
export const KEPT_HOLDINGS = 'Holdings for {date} already in Steward · kept';
export const HOLDINGS_CAPTION = 'Holdings in {file}';                              // plan-owned caption
export const HOLDINGS_LINE = '{account} · {date}: {holdings}';                     // the Look sheet's line
export const LOAN_BALANCE = '{label} {amount}';                                    // the loan check's principal
