"""Enum vocabularies the tool schemas use. Several repeat values from steward (account types, categories, inventory
kinds, flag checks, states, filing statuses); tests/advisor/test_vocab_parity.py keeps them equal."""
from __future__ import annotations

ACCOUNT_TYPES = ("unknown", "checking", "savings", "credit", "brokerage_taxable", "k401", "roth_ira", "traditional_ira",
                 "hsa", "plan529", "mortgage", "property", "loan", "business_checking", "business_credit", "vehicle")
TAX_TREATMENTS = ("taxable", "tax_deferred", "tax_free", "none")
DATA_ARRIVES = ("feed", "statement", "file", "manual")
CATEGORIES = ("groceries", "dining", "housing", "utilities", "transport", "travel", "health", "insurance",
              "loan_payments", "childcare_education", "giving", "subscriptions", "shopping", "personal", "cash_atm",
              "kids", "pets", "home", "gifts", "entertainment", "income", "business_income", "business_expense",
              "taxes", "transfer", "investment", "fees", "interest", "reimbursement", "uncategorized")
# The words Steward shows for each category (web/src/lib/categories.ts and steward.services.spending.LABELS;
# tests/advisor/test_vocab_parity.py keeps them equal), for the about line (Ask about this P14).
CATEGORY_WORDS = {
    "groceries": "Groceries", "dining": "Eating out", "housing": "Housing", "utilities": "Utilities",
    "transport": "Getting around", "travel": "Travel", "health": "Health", "insurance": "Insurance",
    "loan_payments": "Loan payments", "childcare_education": "Childcare and school", "giving": "Giving",
    "subscriptions": "Subscriptions", "shopping": "Shopping", "personal": "Personal", "cash_atm": "Cash and ATM",
    "kids": "Kids", "pets": "Pets", "home": "Home and garden", "gifts": "Gifts", "entertainment": "Fun",
    "income": "Income", "business_income": "Business income", "business_expense": "Business expense",
    "taxes": "Taxes", "transfer": "Transfer", "investment": "Investment activity", "fees": "Fees",
    "interest": "Interest", "reimbursement": "Reimbursement", "uncategorized": "Not sorted yet",
}
BOOK_KINDS = ("household", "parent")
PERSON_ROLES = ("owner", "joint", "business", "member", "child")
FILING_STATUSES = ("single", "mfj", "mfs", "hoh")
STATES = tuple(sorted("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
                      "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()))
CASH_FLOW_BY = ("category", "owner", "business")
CADENCES = ("weekly", "every_2_weeks", "monthly", "yearly")
DIRECTIONS = ("in", "out")
ASSET_CLASSES = ("us_stock", "intl_stock", "bond", "cash", "target_date", "other")
DEBT_KINDS = ("credit_card", "mortgage", "loan", "business_credit")
ITEM_KINDS = ("account", "income", "insurance", "document", "contact")
ITEM_STATUSES = ("confirmed", "needs_checking", "closed")
INCOME_SOURCES = ("social_security", "pension", "annuity", "rmd", "other")
INSURANCE_TYPES = ("medicare", "supplement", "part_d", "long_term_care", "life", "home", "auto")
ITEM_TYPES = tuple(sorted({"checking", "savings", "cd", "brokerage", "ira", "annuity", "credit_card", "loan", "property",
                           *INCOME_SOURCES, *INSURANCE_TYPES, "power_of_attorney", "will", "trust",
                           "healthcare_directive", "beneficiary", "advisor", "attorney", "accountant", "bank_contact",
                           "billing_office"}))
FREQUENCIES = ("monthly", "quarterly", "half_yearly", "yearly")
TOTAL_GROUPS = ("cash", "investments", "retirement", "property", "debts")
FLAG_CHECKS = ("scam", "payee", "large", "unusual", "cash", "monthly", "duplicate", "deposit", "premium", "account",
               "low")
FLAG_SEVERITIES = ("urgent", "normal")
FLAG_STATUSES = ("open", "expected", "handled")
CHECKLIST_ITEMS = ("emergency_fund", "full_match", "no_card_balance", "hsa", "roth_ira", "k401_limit", "taxable")
CHECKLIST_STATUSES = ("done", "not_yet", "cant_tell")
COLLEGE_LEVELS = ("two_year", "in_state_public", "out_of_state_public", "private")
LEVER_KEYS = ("save_more", "spending", "consulting", "gift", "person_2_earnings", "person_1_claim", "person_2_claim",
              "college", "full_ss")
STATE_TAX = ("california", "none", "not_calculated")
CARE_LEVELS = ("at_home", "in_home_help", "assisted_living", "memory_care", "nursing_home")
MEDI_CAL_STATUSES = ("eligible", "over_limit", "after_spend_down")
CARE_ROOMS = ("shared", "private")

_ENUM_WORDS = {w for vocab in (ACCOUNT_TYPES, TAX_TREATMENTS, DATA_ARRIVES, CATEGORIES, PERSON_ROLES, CADENCES,
                               ASSET_CLASSES, DEBT_KINDS, ITEM_KINDS, ITEM_TYPES, FREQUENCIES, TOTAL_GROUPS)
               for v in vocab for w in v.split("_")}
# Words that identify nobody on their own (ruling 4): an identifier made only of these isn't fingerprinted or replaced.
GENERIC_WORDS = frozenset(_ENUM_WORDS | set(
    "the of and a an to for in on at by with my our your her his their its from".split()) | set(
    "husband wife spouse partner mom dad mother father son daughter brother sister aunt uncle grandma grandpa "
    "grandmother grandfather child kid kids".split()) | set(
    "bank card account accounts savings checking credit union federal national trust financial services insurance "
    "mutual life group company inc llc co corp plan fund funds retirement ira roth brokerage joint business house home "
    "manual rewards high yield cd month monthly year yearly social security medicare pension annuity everyday way "
    "new old main first second other personal family ours k".split()) | set(
    # the words of aliases and of the per-turn context, and the calendar, which the context names (ruling 4)
    "person child payee parent today is this book asking household monday tuesday wednesday thursday friday "
    "saturday sunday january february march april may june july august september october november december".split()))


def generic(tokens: list[str]) -> bool:
    """True when every token identifies nobody on its own: a generic word, or a number of 4 digits or fewer. No tokens is not generic: nothing to go on."""
    return bool(tokens) and all(t in GENERIC_WORDS or (t.isdigit() and len(t) <= 4) for t in tokens)
