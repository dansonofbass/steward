// No gendered copy (ledger ruling 1): {name} is the parent's first name and {names} its possessive, both from
// parentName() and possessive() in ./format. The constants keep the plan's names (IS_THIS_HERS, NOT_HERS).
// The inventory's words (docs/design/inventory/README.md and web/mockups/inventory-*.html). {placeholders} are
// filled with fill() from ./format. Server strings (sub-lines, suggestion titles, change rows) are shown as sent.
import type { DataSource, ItemKind, ItemStatus } from './api';

export const STATUS_LABELS: Record<ItemStatus, string> = { confirmed: 'Confirmed', needs_checking: 'Needs checking', closed: 'Closed' };
export const SOURCE_LABELS: Record<DataSource, string> = { feed: 'Bank feed', statement: 'Statements', manual: 'Typed in' };
export const KIND_LABELS: Record<ItemKind, string> = { account: 'Account', income: 'Income', insurance: 'Insurance', document: 'Document', contact: 'Contact' };
export const GROUP_LABELS: Record<ItemKind, string> = { account: 'Accounts', income: 'Income', insurance: 'Policies', document: 'Documents', contact: 'Contacts' };

// List
export const INVENTORY_LEDE = 'Everything {name} has, where it is, and how sure we are about each one.';
export const ADD_AN_ITEM = 'Add an item';
export const IS_THIS_HERS = 'Is this one of {names}?';   // {names}: possessive(parentName(book)), e.g. "Margaret's"
export const IS_THIS_HERS_N = 'Is this one of {names}? {n}';
export const STATUS = 'Status';
export const OWNER = 'Owner';
export const EVERYONE = 'Everyone';
export const SEARCH = 'Search';
export const SEARCH_PLACEHOLDER = 'Name, bank or last 4';
export const ALL = 'All';
export const HEAD = { item: 'Item', owner: 'Owner', status: 'Status', from: 'Data from', updated: 'Updated', amount: 'Amount' };
export const NO_BALANCE = 'No balance yet';
export const A_MONTH = 'a month';
export const TODAY = 'Today';
export const LIST_FOOT = 'Closed items stay listed for the history. Accounts from the bank feed are added here on their own.';
export const CHECKING_FOOT = 'To confirm an item, open it and attach a statement or letter, or link it to an account in the bank feed.';
export const NOTHING_MATCHES = 'Nothing matches.';
export const NOTHING_LISTED = 'Nothing listed yet.';
export const NOTHING_LISTED_BODY = 'Add {names} accounts, income, insurance, documents and contacts. Accounts from the bank feed arrive on their own.';

// Item page
export const BACK_TO_INVENTORY = 'Inventory';
export const ATTACH_A_FILE = 'Attach a file';
export const EDIT = 'Edit';
export const BALANCE = 'Balance';
export const HOLDINGS_ON = 'Holdings on {date}';
export const DETAILS = 'Details';
export const RECENT_TRANSACTIONS = 'Recent transactions';
export const ALL_IN_TRANSACTIONS = 'All transactions for this account';
export const FILES = 'Files';
export const ATTACH = 'Attach';
export const NOTES = 'Notes';
export const HISTORY = 'History';
export const CHANGE_RECORD = 'Change record';
export const DOWNLOAD = 'Download';
export const DOWNLOAD_NAME = 'Download {name}';
export const REMOVE_NAME = 'Remove {name}';
export const REMOVE = 'Remove';
export const REMOVE_FILE_TITLE = 'Remove {name}?';
export const REMOVE_FILE_BODY = 'It comes off this item. The change record keeps a line saying so.';
export const FILE_REMOVED = 'Removed {name}.';
export const KEEP_IT = 'Keep it';
export const NO_FILES = 'No files yet.';
export const NO_NOTES = 'No notes.';
export const F = {
  institution: 'Institution', where: 'Where it is', type: 'Type', last4: 'Last 4', accountNumber: 'Account number',
  policyNumber: 'Policy number', owner: 'Owner', dataFrom: 'Data from', loginKeptIn: 'Login kept in',
  moneyInHere: 'Money in here', paidFromHere: 'Paid from here', added: 'Added', amount: 'Amount',
  usuallyArrives: 'Usually arrives', landsIn: 'Lands in', matchedBy: 'Matched by', premium: 'Premium',
  floor: 'Low-balance floor', paidFrom: 'Paid from', renewal: 'Renewal', signed: 'Signed', preparedBy: 'Prepared by', scan: 'Scan',
  originalKeptIn: 'Original kept in', role: 'Role', firm: 'Firm', phone: 'Phone', email: 'Email', linkedItems: 'Linked items',
};
export const NOT_KNOWN = 'Not known';
export const NO_LOGIN = 'No online login yet';
export const ATTACHED = 'Attached';
export const NOT_ATTACHED = 'Not attached';
export const AROUND_THE = 'Around the {day}';
export const LAST_PAID = 'last paid {date}';
export const SHOW = 'Show';
export const HIDE = 'Hide';
export const WHY_CHECKING = 'Why it needs checking:';
export const TO_CONFIRM_BY_KIND: Record<string, string> = {
  insurance: 'To confirm it, attach the policy or a recent statement, then mark it Confirmed.',
  account: 'To confirm it, attach a recent statement, then mark it Confirmed.',
  income: 'To confirm it, attach a recent pay stub or a letter about it, then mark it Confirmed.',
  document: 'To confirm it, attach a copy, then mark it Confirmed.',
  contact: 'To confirm it, check the details with them, then mark it Confirmed.',
};
export const MARK_CONFIRMED = 'Mark Confirmed';
export const CLOSED_LINE = 'Closed {date}.';
export const REOPEN = 'Reopen';
export const PER_WORDS: Record<string, string> = { monthly: 'a month', quarterly: 'every 3 months', half_yearly: 'every 6 months', yearly: 'a year' };

// Form
export const ADD_TITLE = 'Add an item';
export const EDIT_TITLE = 'Edit {name}';
export const WHAT_IS_IT = 'What is it?';
export const KIND = 'Kind';
export const FROM_TAX_FORM = 'From a tax form (1099 or SSA-1099)';
export const SECTION: Record<ItemKind, string> = { account: 'The account', income: 'The income', insurance: 'The policy', document: 'The document', contact: 'The contact' };
export const NAME = 'Name';
export const NAME_HINT = 'How it shows in the inventory.';
export const INSURER = 'Insurer';
export const PAYER = 'Payer';
export const NUMBER_HINT = 'Lists and emails show only the last 4.';
export const NUMBER_HINT_SHOWN = 'Lists and emails show only the last 4: ••{last4}.';
export const NUMBER_KEEP = 'Leave blank to keep ••{last4}.';
export const WHOSE = 'Whose is it?';
export const MONEY_SECTION: Record<'income' | 'insurance', string> = { income: 'Amount', insurance: 'Premium' };
export const AMOUNT = 'Amount';
// Care works out the tax on a pension or annuity, so it is entered before withholding (parent care final review M8).
export const AMOUNT_BEFORE_TAX = 'Amount before tax is withheld';
export const HOW_OFTEN = 'How often';
export const FREQUENCY_LABELS: Record<string, string> = { monthly: 'Monthly', quarterly: 'Every 3 months', half_yearly: 'Every 6 months', yearly: 'Yearly' };
export const USUAL_DAY = 'Usual day of the month';
export const USUAL_DAY_HINT: Record<'income' | 'insurance', string> = { income: 'Used to spot a missed deposit.', insurance: 'Used to spot a missed payment.' };
export const RENEWAL_DATE = 'Renewal date';
export const RENEWAL_HINT = "Leave blank if you don't know.";
export const MATCH_TEXT = 'As the bank shows it';
export const MATCH_HINT = "Words from the bank's description, used to find these transactions.";
export const NONE = 'None';
export const HOW_SURE = 'How sure are we?';
export const CONFIRMED_HINT: Record<ItemKind, string> = {
  account: "We've seen a statement or the bank feed.", income: "We've seen a deposit or a letter about it.",
  insurance: "We've seen the policy, a statement or a payment in the bank feed.", document: "We've seen the document or a copy.",
  contact: '',
};
export const NEEDS_CHECKING_HINT = "We think it exists but haven't seen proof.";
export const WHY_FIELD = 'Why it needs checking';
export const WHY_FIELD_HINT = 'For example: typed in from a letter found in {names} mail.';
export const OTHER = 'Other';
export const LOGIN_PLACEHOLDER = 'e.g. family password manager, entry "Globe Mutual"';
export const LOGIN_HINT = 'Where the login is kept, never the password itself.';
export const DATA_FROM_Q = 'Data from';
export const DATA_FROM_HINT = 'Bank feed accounts arrive on their own.';
export const BALANCE_ON = 'Balance as of';
export const DATE_SIGNED = 'Date signed';
export const LOOKS_AFTER = 'Items they look after';
export const ADD_ITEM = 'Add item';
export const SAVE = 'Save';
export const CANCEL = 'Cancel';
export const WHY_CHANGE = 'Why the change? (optional)';
export const WHY_CHANGE_HINT = 'Saved with this change in the change record.';
export const SUGGESTION_GONE = "That suggestion isn't here any more. Someone may have answered it already. You can still add the item below.";
export const CLOSE_ITEM = 'Close this item';
export const CLOSE_TITLE = 'Close {name}?';
export const CLOSE_BODY = 'It stays in the inventory under Closed, with its files and history. Nothing is deleted.';
export const CLOSED_ON = 'Closed on';
export const CLOSE_WHY = 'Why';
export const CLOSE_WHY_PLACEHOLDER = 'e.g. policy cancelled, account moved to Fidelity';
export const CLOSE_CONFIRM = 'Close item';
export const KEEP_OPEN = 'Keep it open';
export const CHOOSE = 'Choose…';

// Type options (keys match src/steward/inventory/kinds.py)
export const TYPE_OPTIONS: Record<ItemKind, [string, string][]> = {
  account: [['checking', 'Checking'], ['savings', 'Savings'], ['cd', 'CD'], ['brokerage', 'Brokerage'], ['ira', 'IRA'], ['annuity', 'Annuity'], ['credit_card', 'Credit card'], ['loan', 'Loan'], ['property', 'Property']],
  income: [['social_security', 'Social Security'], ['pension', 'Pension'], ['annuity', 'Annuity'], ['rmd', 'RMD'], ['other', 'Other']],
  insurance: [['medicare', 'Medicare'], ['supplement', 'Medicare supplement'], ['part_d', 'Medicare Part D'], ['long_term_care', 'Long-term care'], ['life', 'Life'], ['home', 'Homeowners'], ['auto', 'Auto']],
  document: [['power_of_attorney', 'Power of attorney'], ['will', 'Will'], ['trust', 'Trust'], ['healthcare_directive', 'Healthcare directive'], ['beneficiary', 'Beneficiary designation'], ['other', 'Other']],
  contact: [['advisor', 'Financial advisor'], ['attorney', 'Attorney'], ['accountant', 'Accountant'], ['bank_contact', 'Bank contact'], ['billing_office', "Doctor's billing office"], ['other', 'Other']],
};
export const TYPE_LABEL: Record<ItemKind, string> = { account: 'Type', income: 'Source', insurance: 'Type', document: 'Type', contact: 'Role' };

// Suggestions
export const SUG_LEDE = 'Steward found these in {names} transactions and tax forms, and none of them match an item yet. {n} to go through.';
export const ADD_AS = 'Add as {kind}';
export const ALREADY_LISTED = 'Already listed';
export const NOT_HERS = 'Not {names}';
export const UNDO = 'Undo';
export const WHICH_ITEM = 'Which item is it?';
export const WILL_COUNT = "The {n} {payer} {noun} will count toward the item you pick, and Steward won't suggest this payer again.";
export const SEARCH_ITEMS = 'Search {names} items';
export const LIKELY = 'Likely, same institution';
export const OTHER_ITEMS = 'Other income and accounts';
export const ALSO_CONFIRM = 'Also mark {name} Confirmed';
export const CONFIRM_HINT = 'Regular {noun} from {payer} show it exists.';
export const LINK = 'Link';
export const NOTHING_TO_GO_THROUGH = 'Nothing to go through. New suggestions show up after a bank sync, an import or a tax form.';
export const DISMISSED_LEDE = "Payers answered Not {names}. Steward doesn't suggest them again.";
export const SUGGEST_AGAIN = 'Suggest again';
export const NONE_DISMISSED = 'Nothing dismissed.';
export const DISMISSED_ON = '{kind} · {date} by {who}';
export const DISMISSED_ON_DATE = '{kind} · {date}';
export const DISMISSED_ON_WHO = '{kind} · by {who}';

// Attach
export const ATTACH_TO = 'To {label}.';
export const ATTACH_TO_CHECKING = 'To {label}, which Needs checking.';
export const DROP = 'Drop a file here';
export const CHOOSE_FILE = 'Choose a file';
export const ALLOWED = 'PDF, PNG, JPEG, HEIC or CSV, up to 25 MB. Stored encrypted with this book.';
export const UPLOADING = 'Uploading · {sent} of {total}';
export const ATTACHED_LINE = 'Attached · {label} · {size}';
export const STOP = 'Stop';
export const MARK_ITEM_CONFIRMED = 'Mark {name} Confirmed';
export const MARK_HINT = 'A statement or contract from {institution} shows it exists.';
export const DONE = 'Done';
export const LOOKS_LIKE_TAX = 'This looks like a tax form';
export const LOOKS_LIKE_TAX_BODY = "Type in its boxes and Steward will look for accounts and income {name} doesn't have listed.";
export const TYPE_IT_IN = 'Type it in';

// Tax forms
export const TAX_TITLE = 'Type in a tax form';
export const TAX_LEDE = 'Copy the boxes from the form. Steward checks the payer against {names} items and suggests anything missing.';
export const FORM = 'Form';
export const FORMS = ['1099-INT', '1099-DIV', '1099-R', 'SSA-1099'] as const;
export const FORM_HINTS: Record<string, string> = {
  '1099-INT': 'Interest from a bank, credit union or savings bonds.', '1099-DIV': 'Dividends and fund distributions from a brokerage or fund.',
  '1099-R': 'Pensions, annuities, IRA withdrawals and RMDs.', 'SSA-1099': 'Social Security benefits for the year.',
};
export const FORM_BOXES: Record<string, [string, string, string][]> = {   // key, "Box 1", name
  '1099-INT': [['box_1', 'Box 1', 'Interest income'], ['box_4', 'Box 4', 'Federal income tax withheld']],
  '1099-DIV': [['box_1a', 'Box 1a', 'Total ordinary dividends'], ['box_1b', 'Box 1b', 'Qualified dividends'], ['box_2a', 'Box 2a', 'Total capital gain distributions'], ['box_4', 'Box 4', 'Federal income tax withheld']],
  '1099-R': [['box_1', 'Box 1', 'Gross distribution'], ['box_2a', 'Box 2a', 'Taxable amount'], ['box_4', 'Box 4', 'Federal income tax withheld'], ['box_7', 'Box 7', 'Distribution code']],
  'SSA-1099': [['box_3', 'Box 3', 'Benefits paid'], ['box_5', 'Box 5', 'Net benefits'], ['medicare', 'Medicare premiums', "from Box 3's description"]],
};
export const TAX_YEAR = 'Tax year';
export const RECIPIENT = 'Recipient';
export const PAYERS_NAME = "Payer's name";
export const LAST4_IF_SHOWN = 'Account number, last 4 (if shown)';
export const ATTACH_THE_FORM = 'Attach the form';
export const ATTACHED_WORD = 'attached';
export const SAVE_AND_CHECK = 'Save and check {names} items';
export const IMPORT_CSV = 'Import several from a CSV';
export const CSV_HINT = 'Columns: form, tax_year, recipient, payer, last4, box_1, box_1a, box_1b, box_2a, box_3, box_4, box_5, box_7, medicare. Amounts in dollars.';
export const GO_TO_SUGGESTIONS = 'Go to Is this one of {names}?';
export const TYPE_ANOTHER = 'Type in another';
export const CSV_SAVED = '{n} forms saved.';

// Home
export const TO_DO = 'To do';
export const MONEY_IN_OUT = 'Money in and out';
export const NET_WORTH_KNOWN = 'Net worth, known items';
export const NEEDS_CHECKING_N = 'Needs checking: {n}';
export const SEE_THEM = 'See them';
export const GO_THROUGH = 'Go through them';
export const WHAT_SHE_HAS = 'What {name} has';
export const COMING_IN = 'Money coming in each month';
export const GOING_OUT = 'Money going out regularly';
export const RECENT_CHANGES = 'Recent changes';
export const NO_CHANGES_YET = 'No changes yet.';

// Change record
export const CHANGES_LEDE = "Every change a manager makes to {book}, newest first. It can't be edited or deleted, and everyone in the book can see it.";
export const PERSON = 'Person';
export const KIND_OF_CHANGE = 'Kind of change';
export const ALL_CHANGES = 'All changes';
export const KIND_FILTERS: [string, string][] = [['watching', 'Flags and watching'], ['care', 'Care'], ['items', 'Items'], ['files', 'Files'], ['suggestions', 'Suggestions'], ['transactions', 'Transactions'], ['imports', 'Imports'], ['members', 'Members'], ['bank_feed', 'Bank feed']];
export const SHOW_OLDER = 'Show older';
export const CHANGES_FOOT = "Changes the bank feed makes on its own (new transactions, balances) aren't listed here; each sync is in Settings → Banks.";
export const FLOOR = 'Low-balance floor';
export const FLOOR_HINT = 'Leave blank for no floor. Look into flags the account when its balance falls below this.';
export const FLOOR_TYPES = ['checking', 'savings', 'cd'];

export const LTC_SECTION = 'Long-term care benefit';
export const LTC = {
  benefit: 'Benefit', per: 'Paid', perDay: 'A day', perMonth: 'A month', waiting: 'Waiting period, days',
  waitingHint: 'Called the elimination period on the policy.', pool: 'Total benefit',
  poolHint: 'Leave blank if the policy gives benefit years instead.', years: 'Benefit years',
  rider: 'Inflation protection, % a year', riderHint: 'Leave blank if the policy has none.',
};
export const F_LTC = {
  benefit: 'Benefit', waiting: 'Waiting period', days: '{n} days', pool: 'Total benefit', yearsOf: '{n} years of benefit',
  rider: 'Inflation protection', riderPct: '{pct}% a year', none: 'None',
};
