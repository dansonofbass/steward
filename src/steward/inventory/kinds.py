"""The inventory's words (spec 3.1; the item form in docs/design/inventory/README.md). Keys are stored, labels are
shown, and words are the label as it reads inside a sentence."""
from __future__ import annotations

from steward.db.models import AccountType

KIND_LABELS = {"account": "Account", "income": "Income", "insurance": "Insurance", "document": "Document",
               "contact": "Contact"}
GROUP_LABELS = {"account": "Accounts", "income": "Income", "insurance": "Insurance", "document": "Documents",
                "contact": "Contacts"}
STATUS_LABELS = {"confirmed": "Confirmed", "needs_checking": "Needs checking", "closed": "Closed"}
SOURCE_LABELS = {"feed": "Bank feed", "statement": "Statements", "manual": "Typed in"}

ACCOUNT_TYPES = (("checking", "Checking", "checking"), ("savings", "Savings", "savings"), ("cd", "CD", "CD"),
                 ("brokerage", "Brokerage", "brokerage"), ("ira", "IRA", "IRA"), ("annuity", "Annuity", "annuity"),
                 ("credit_card", "Credit card", "credit card"), ("loan", "Loan", "loan"),
                 ("property", "Property", "property"))
INCOME_SOURCES = (("social_security", "Social Security", "Social Security"), ("pension", "Pension", "pension"),
                  ("annuity", "Annuity", "annuity"), ("rmd", "RMD", "RMD"), ("other", "Other", "other"))
INSURANCE_TYPES = (("medicare", "Medicare", "Medicare"), ("supplement", "Medicare supplement", "Medicare supplement"),
                   ("part_d", "Medicare Part D", "Medicare Part D"),
                   ("long_term_care", "Long-term care", "long-term care"), ("life", "Life", "life"),
                   ("home", "Homeowners", "homeowners"), ("auto", "Auto", "auto"))
DOCUMENT_TYPES = (("power_of_attorney", "Power of attorney", "power of attorney"), ("will", "Will", "will"),
                  ("trust", "Trust", "trust"), ("healthcare_directive", "Healthcare directive", "healthcare directive"),
                  ("beneficiary", "Beneficiary designation", "beneficiary designation"), ("other", "Other", "other"))
CONTACT_ROLES = (("advisor", "Financial advisor", "financial advisor"), ("attorney", "Attorney", "attorney"),
                 ("accountant", "Accountant", "accountant"), ("bank_contact", "Bank contact", "bank contact"),
                 ("billing_office", "Doctor's billing office", "doctor's billing office"), ("other", "Other", "other"))
TYPES_BY_KIND = {"account": ACCOUNT_TYPES, "income": INCOME_SOURCES, "insurance": INSURANCE_TYPES,
                 "document": DOCUMENT_TYPES, "contact": CONTACT_ROLES}
TYPE_FIELD = {"account": "type", "income": "source", "insurance": "type", "document": "type", "contact": "role"}

FREQUENCIES = {"monthly": 1, "quarterly": 3, "half_yearly": 6, "yearly": 12}
FREQUENCY_LABELS = {"monthly": "Monthly", "quarterly": "Every 3 months", "half_yearly": "Every 6 months",
                    "yearly": "Yearly"}
FREQUENCY_WORDS = {"monthly": "monthly", "quarterly": "every 3 months", "half_yearly": "every 6 months",
                   "yearly": "yearly"}
PER_SUFFIX = {"monthly": "mo", "quarterly": "3 mo", "half_yearly": "6 mo", "yearly": "yr"}
INCOME_FREQUENCIES = ("monthly", "quarterly", "yearly")

# Ruling 6: the linked account row gets the nearest existing type.
ACCOUNT_TYPE_TO_ACCOUNT = {
    "checking": AccountType.checking, "savings": AccountType.savings, "cd": AccountType.savings,
    "brokerage": AccountType.brokerage_taxable, "ira": AccountType.traditional_ira,
    "annuity": AccountType.brokerage_taxable, "credit_card": AccountType.credit, "loan": AccountType.loan,
    "property": AccountType.property,
}
ACCOUNT_TO_ACCOUNT_TYPE = {
    AccountType.checking: "checking", AccountType.savings: "savings", AccountType.credit: "credit_card",
    AccountType.brokerage_taxable: "brokerage", AccountType.traditional_ira: "ira", AccountType.roth_ira: "ira",
    AccountType.k401: "ira", AccountType.mortgage: "loan", AccountType.loan: "loan", AccountType.property: "property",
    AccountType.business_checking: "checking", AccountType.business_credit: "credit_card",
    AccountType.hsa: "savings", AccountType.plan529: "brokerage",
}
# Ruling 7.
TOTAL_GROUP = {"checking": "cash", "savings": "cash", "cd": "cash", "brokerage": "investments", "ira": "retirement",
               "annuity": "retirement", "property": "property", "credit_card": "debts", "loan": "debts"}
TOTALS = (("cash", "Cash"), ("investments", "Investments"), ("retirement", "Retirement"), ("property", "Property"),
          ("debts", "Debts"))
DEBT_TYPES = frozenset({"credit_card", "loan"})
FLOOR_TYPES = frozenset({"checking", "savings", "cd"})   # watching ruling 11: the accounts that can have a floor


def _find(kind: str, key: object) -> tuple[str, str, str] | None:
    return next((t for t in TYPES_BY_KIND.get(kind, ()) if t[0] == key), None)


def type_label(kind: str, key: object) -> str | None:
    t = _find(kind, key)
    return t[1] if t else None


def type_word(kind: str, key: object) -> str | None:
    t = _find(kind, key)
    return t[2] if t else None


def monthly_cents(amount_cents: int | None, frequency: str | None) -> int | None:
    """A premium or deposit as a monthly figure, rounded half up per item (the overview sums these)."""
    if amount_cents is None or frequency not in FREQUENCIES:
        return None
    months = FREQUENCIES[frequency]
    return (2 * amount_cents + months) // (2 * months)


CONTENT_LABELS = {"application/pdf": "PDF", "image/png": "PNG", "image/jpeg": "JPEG", "image/heic": "HEIC",
                  "text/csv": "CSV"}
