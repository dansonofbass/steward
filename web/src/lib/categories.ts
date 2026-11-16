import { CAT_EVERYDAY, CAT_FAMILY, CAT_HOME_BILLS, CAT_MONEY_IN, CAT_OTHER, GROUP_BUSINESS, GROUP_LOANS, GROUP_CARDS, GROUP_EVERYDAY, GROUP_HOME, GROUP_INVESTING, GROUP_KIDS, GROUP_OTHER, GROUP_RETIREMENT, GROUP_SAVINGS } from './copy';

export const CATEGORY_LABELS: Record<string, string> = {
  groceries: 'Groceries',
  dining: 'Eating out',
  housing: 'Housing',
  utilities: 'Utilities',
  transport: 'Getting around',
  travel: 'Travel',
  health: 'Health',
  insurance: 'Insurance',
  loan_payments: 'Loan payments',
  childcare_education: 'Childcare and school',
  giving: 'Giving',
  subscriptions: 'Subscriptions',
  shopping: 'Shopping',
  personal: 'Personal',
  cash_atm: 'Cash and ATM',
  kids: 'Kids',
  pets: 'Pets',
  home: 'Home and garden',
  gifts: 'Gifts',
  entertainment: 'Fun',
  income: 'Income',
  business_income: 'Business income',
  business_expense: 'Business expense',
  taxes: 'Taxes',
  transfer: 'Transfer',
  investment: 'Investment activity',
  fees: 'Fees',
  interest: 'Interest',
  reimbursement: 'Reimbursement',
  uncategorized: 'Not sorted yet',
};

export const CATEGORY_ORDER: string[] = [
  ...Object.keys(CATEGORY_LABELS).filter((k) => k !== 'uncategorized'),
  'uncategorized',
];

/** The category picker's sections, in the order people look: what they buy day to day, the home and its bills, family,
 *  money coming in, then the rest. Every category but Not sorted yet is in exactly one (categories.test.ts). */
export const CATEGORY_GROUPS: readonly { name: string; keys: readonly string[] }[] = [
  { name: CAT_EVERYDAY, keys: ['groceries', 'dining', 'transport', 'shopping', 'personal', 'entertainment', 'gifts', 'travel', 'cash_atm'] },
  { name: CAT_HOME_BILLS, keys: ['housing', 'utilities', 'home', 'insurance', 'subscriptions', 'loan_payments'] },
  { name: CAT_FAMILY, keys: ['health', 'kids', 'pets', 'childcare_education', 'giving'] },
  { name: CAT_MONEY_IN, keys: ['income', 'interest', 'business_income', 'reimbursement'] },
  { name: CAT_OTHER, keys: ['business_expense', 'taxes', 'fees', 'transfer', 'investment'] },
];

export function label(key: string): string {
  return CATEGORY_LABELS[key] ?? key;
}

const GROUPS: Record<string, string> = {
  checking: GROUP_EVERYDAY,
  savings: GROUP_SAVINGS,
  credit: GROUP_CARDS,
  brokerage_taxable: GROUP_INVESTING,
  k401: GROUP_RETIREMENT,
  roth_ira: GROUP_RETIREMENT,
  traditional_ira: GROUP_RETIREMENT,
  hsa: GROUP_RETIREMENT,
  plan529: GROUP_KIDS,
  mortgage: GROUP_HOME,
  loan: GROUP_LOANS,
  property: GROUP_HOME,
  business_checking: GROUP_BUSINESS,
  business_credit: GROUP_BUSINESS,
  unknown: GROUP_OTHER,
};

export function groupOf(type: string): string {
  return GROUPS[type] ?? GROUP_OTHER;
}

export const UNSORTED = 'uncategorized';

/** Everyday words per category (sorting redesign, decision 6): typing the start of any of them finds the category. A
 *  phrase matches word by word. The spec's first pass, refined: dining drops "ubereats" (it ranked Eating out above
 *  Getting around for "uber") and gains "grubhub"; Interest gains "yield"; Not sorted yet gains "unsure" and "later". */
export const CATEGORY_WORDS: Record<string, readonly string[]> = {
  groceries: ['grocery', 'supermarket', 'costco', 'kroger', 'aldi', 'trader', 'market', 'food'],
  dining: ['restaurant', 'cafe', 'coffee', 'starbucks', 'takeout', 'doordash', 'grubhub', 'bar', 'lunch', 'dinner', 'pizza'],
  transport: ['gas', 'fuel', 'shell', 'chevron', 'parking', 'uber', 'lyft', 'taxi', 'transit', 'bus', 'train', 'toll', 'car wash', 'auto'],
  shopping: ['amazon', 'target', 'walmart', 'clothes', 'store', 'online'],
  personal: ['haircut', 'salon', 'barber', 'gym', 'beauty', 'spa'],
  entertainment: ['movies', 'netflix', 'concert', 'games', 'tickets', 'books', 'music'],
  gifts: ['present', 'birthday', 'christmas', 'wedding'],
  travel: ['hotel', 'airbnb', 'flight', 'airline', 'rental car', 'vacation'],
  cash_atm: ['atm', 'cash', 'withdrawal'],
  housing: ['rent', 'mortgage', 'hoa'],
  utilities: ['electric', 'power', 'water', 'gas bill', 'internet', 'phone', 'trash', 'sewer'],
  home: ['hardware', 'home depot', 'lowes', 'garden', 'repair', 'furniture', 'plumber'],
  insurance: ['auto insurance', 'home insurance', 'life', 'premium'],
  subscriptions: ['spotify', 'streaming', 'membership', 'apple', 'google', 'software'],
  loan_payments: ['car payment', 'student loan', 'auto loan'],
  health: ['doctor', 'pharmacy', 'dentist', 'cvs', 'walgreens', 'copay', 'hospital'],
  kids: ['toys', 'diapers', 'allowance'],
  pets: ['vet', 'petco', 'petsmart', 'dog', 'cat', 'grooming'],
  childcare_education: ['daycare', 'tuition', 'school', 'babysitter'],
  giving: ['donation', 'charity', 'church', 'tithe'],
  income: ['paycheck', 'salary', 'payroll', 'deposit', 'wages'],
  interest: ['dividend', 'savings interest', 'yield'],
  business_income: ['client', 'invoice', 'revenue'],
  reimbursement: ['reimbursement', 'expense', 'expenses', 'repaid', 'per diem'],
  business_expense: ['office', 'supplies', 'software', 'work'],
  taxes: ['irs', 'tax', 'property tax', 'state tax'],
  fees: ['fee', 'late fee', 'overdraft', 'finance charge', 'card interest'],
  transfer: ['transfer', 'card payment', 'savings', 'venmo', 'zelle'],
  investment: ['brokerage', 'stocks', '401k', 'ira', 'betterment'],
  uncategorized: ['unsure', 'later'],
};

/** Accents and case folded: "Café" -> "cafe". */
export const fold = (s: string) => s.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase();
const wordsOf = (s: string) => fold(s).split(/[^\p{L}\p{N}]+/u).filter(Boolean);

/** The categories a search finds (sorting redesign, Matching): every typed word must start a word of the label or of
 *  its everyday words. Label matches first, then everyday-word matches; within each, the usual categories first, then
 *  the groups' visible order. */
export function findCategories(q: string, usual: readonly string[] = [], withUnsorted = false): string[] {
  const typed = wordsOf(q);
  const keys = [...CATEGORY_GROUPS.flatMap((g) => g.keys), ...(withUnsorted ? [UNSORTED] : [])];
  const hits = (pool: string[]) => typed.every((w) => pool.some((p) => p.startsWith(w)));
  const rank = (k: string) => (usual.includes(k) ? usual.indexOf(k) : usual.length + keys.indexOf(k));
  const byRank = (a: string, b: string) => rank(a) - rank(b);
  const byLabel = keys.filter((k) => hits(wordsOf(label(k))));
  const byWord = keys.filter((k) => !byLabel.includes(k)
    && hits([...wordsOf(label(k)), ...(CATEGORY_WORDS[k] ?? []).flatMap(wordsOf)]));
  return [...byLabel.sort(byRank), ...byWord.sort(byRank)];
}
