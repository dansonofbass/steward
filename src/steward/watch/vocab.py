"""The words and numbers of watching (spec 4.1-4.3; docs/design/watching/README.md "The frame"; watching decisions).
Keys are stored; labels are shown. Every rule a plan ruling settled has its constant here."""
from __future__ import annotations

from datetime import time

from steward.inventory.present import usd

CHECK_LABELS = {
    "scam": "Scam pattern", "payee": "New payee", "large": "Large amount", "unusual": "Unusual for {name}",
    "cash": "Cash", "monthly": "New monthly charge", "duplicate": "Duplicate", "deposit": "Missing deposit",
    "premium": "Missed premium", "account": "New account", "low": "Low balance",
}
CHECK_ICONS = {
    "scam": "octagon-alert", "premium": "calendar-x", "deposit": "calendar-x", "payee": "user-plus",
    "large": "banknote", "unusual": "circle-alert", "cash": "coins", "monthly": "repeat", "duplicate": "copy",
    "account": "landmark", "low": "trending-down",
}
# Most serious first: a flag is named by the first of its checks in this order, urgent before normal (decision 3).
RANK = ("scam", "deposit", "premium", "large", "payee", "unusual", "cash", "monthly", "duplicate", "account", "low")
SILENCED = frozenset({"payee", "large", "unusual", "monthly"})    # decision 1
STATUS_LABELS = {"open": "Open", "checking": "Still checking", "expected": "Expected", "handled": "Handled",
                 "arrived": "Arrived"}
STATUS_ICONS = {"open": "circle", "checking": "hourglass", "expected": "circle-check", "handled": "check",
                "arrived": "calendar-check"}
DONE = frozenset({"expected", "handled", "arrived"})
NOT_DONE = ("open", "checking")

# Decision 10: one line on what the check looks for, about the check and never the person.
WHY = {
    "scam": "This check flags every gift card, wire transfer, crypto exchange, money-transfer service and remote "
            "computer support payment, because those are the payments scammers ask for.",
    "payee": "This check flags money sent to someone this book hasn't paid in the last 18 months. Zelle, wire, check "
             "and bill-pay payments over $200 are urgent.",
    "large": "This check flags any payment of {large} or more, the amount set in Settings → Watching.",
    "unusual": "This check flags a payment of more than $100 that is over 3 times the usual amount for its category "
               "in the last 12 months.",
    "cash": "This check flags the cash withdrawal that takes a month past the usual monthly cash total, "
            "or a first withdrawal of the cash alert amount or more when there is usually none.",
    "monthly": "This check flags a merchant charging about the same amount two months in a row after not charging "
               "before, the way a new subscription starts.",
    "duplicate": "This check flags the same amount to the same place within 3 days, which is how a double charge looks.",
    "deposit": "This check flags an income item's deposit that hasn't arrived 5 days after its usual day.",
    "premium": "This check flags an insurance premium that hasn't left 5 days after its usual day, because a missed "
               "premium can end a policy.",
    "account": "This check flags an account the bank feed reports that wasn't in the inventory.",
    "low": "This check flags an account whose balance falls below the floor set for it.",
}

METHOD_WORDS = {"card": "", "zelle": "by Zelle", "wire": "by wire", "bill_pay": "by bill pay", "check": "by check"}
METHOD_TITLES = {"zelle": "Zelle", "wire": "Wire", "bill_pay": "Bill pay", "check": "Check"}
NO_MEDIAN_CATEGORIES = frozenset({"uncategorized", "transfer", "income", "business_income", "interest"})

DEFAULT_LARGE_CENTS = 50_000          # spec 4.1: "default $500"
DEFAULT_CASH_FLOOR_CENTS = 20_000     # leftovers row 21: with no usual cash, alert from this withdrawal up
CARD_PAYEE_MIN_CENTS = 5_000          # ruling 1
URGENT_PAYEE_OVER_CENTS = 20_000      # spec 4.1: "over $200"
NEW_PAYEE_DAYS = 548                  # 18 months
STALE_DAYS = 60                       # ruling 2
BASELINE_DAYS = 60                    # ruling 2
BAND_PCT = 25                         # decision 1
GRACE_DAYS = 5                        # spec 4.1
EARLY_DAYS = 10                       # ruling 3
UNUSUAL_TIMES = 3
UNUSUAL_MIN_CENTS = 10_000
UNUSUAL_MIN_SAMPLES = 3               # ruling 16
CASH_MIN_MONTHS = 2                   # ruling 12
MONTHLY_GAP = (25, 35)                # ruling 16
MONTHLY_SLACK_CENTS = 100
DUPLICATE_DAYS = 3
NOTE_MAX = 300                        # ruling 10
DAILY_AT = time(6, 30)                # ruling 17
SUMMARY_AT = time(7, 0)               # decision 8
RETRY_MINUTES = 30                    # spec 8: 3 tries over an hour
TRIES = 3


def check_label(check: str, name: str) -> str:
    return CHECK_LABELS[check].format(name=name)


def why(check: str, large_cents: int) -> str:
    return WHY[check].format(large=usd(large_cents))
