import re
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from steward.db.models import Account, AccountType, CategorySource, Transaction
from steward.services.categorizer_client import BATCH, Guess, ModelClient, business_of
from steward.services.transactions import normalize, sorting_rule, tidy


@dataclass(frozen=True)
class Suggestion:
    merchant: str | None
    category: str
    is_business: bool | None
    source: CategorySource
    business_hint: int | None = None
    guess: str | None = None        # phase 12 decision 4: the model's best guess when it wasn't sure
    guess_pct: int | None = None
    asked: bool = False             # ruling 14: the model answered about this row (sorted it, guessed, or couldn't tell)


def _r(p: str) -> re.Pattern:
    return re.compile(p)


def _out(p: str) -> re.Pattern:
    """A rule for money going out only: rules never see the amount, so a description of money coming in (a deposit, a
    refund, a loan's funding or disbursement, a reversal) doesn't match."""
    return re.compile(r"^(?!.*\b(?:DEPOSIT|REFUND|FUNDING|DISBURS\w*|REVERSAL|CREDIT ADJ)\b)(?:.*?)(?:" + p + ")")


INCOME_TAX = _r(r"\bIRS\b|USTREAS|FRANCHISE TAX|\bFTB\b")      # Phase 11c: the engine works income tax out, so vault_flows leaves it out of spending


# (pattern on the tidy()-cleaned description, category, merchant or None); first match wins
BUILTIN: list[tuple[re.Pattern, str, str | None]] = [
    (_r(r"PAYROLL|DIRECT DEP|DIR DEP"), "income", None),
    (_r(r"MORTGAGE|HOMELOAN|HOME LOAN"), "housing", None),
    (_r(r"\bZELLE\b"), "uncategorized", "Zelle"),
    (_r(r"\bVENMO\b"), "uncategorized", "Venmo"),
    (_r(r"CASH APP"), "uncategorized", "Cash App"),
    (_r(r"\bPAYPAL\b"), "uncategorized", "PayPal"),
    (_r(r"PAYMENT THANK YOU|AUTOPAY PAYMENT|ONLINE PAYMENT .*CARD|TRANSFER (TO|FROM)|OWNER DRAW"
        r"|\b(IRA|401K|401\(K\)|ROTH|HSA|529) CONTRIBUTION\b"
        # Phase 12 decision 9: the issuers' checking-side wording for a card payment.
        r"|\bCREDIT CRD AUTOPAY\b|\bCRD EPAY\b|\bCRD AUTOPAY\b|\bEPAYMENT\b|\bE-PAYMENT\b|\bCRCARDPMT\b|\bCARD PMT\b"
        r"|\bCARD PAYMENT\b|\bCITI AUTOPAY\b|\bAMEX EPAYMENT\b|\bDISCOVER E-PAYMENT\b|\bAPPLECARD GSBANK\b"),
     "transfer", None),
    (INCOME_TAX, "taxes", None),
    (_r(r"\bATM\b.*\bFEE\b|\bATM FEE\b|NON-?NETWORK ATM"), "fees", None),
    (_out(r"\bATM\b|\bCASH WITHDRAWAL\b|\bCASH W/D\b"), "cash_atm", None),
    (_out(r"\b(?:AUTO LOAN|CAR LOAN|TOYOTA FIN\w*|HONDA FIN\w*|AMERICAN HONDA FIN\w*|FORD CREDIT|FORD MOTOR CR\w*"
          r"|GM FINANCIAL|ALLY AUTO|ALLY PAYMT|NISSAN MOTOR ACCEPT\w*|HYUNDAI MOTOR FIN\w*|KIA MOTORS FIN\w*"
          r"|SANTANDER CONSUMER|CAPITAL ONE AUTO (?:FIN\w*|LOAN)|NAVIENT|NELNET|SALLIE MAE|MOHELA|AIDVANTAGE"
          r"|STUDENT LOAN|SOFI LOAN|PERSONAL LOAN)\b"),
     "loan_payments", None),
    (_r(r"\bINTEREST\b"), "interest", None),
    (_r(r"COSTCO|WHOLE FOODS|TRADER JOE|SAFEWAY|KROGER|WALMART"), "groceries", None),
    (_r(r"AMAZON|AMZN"), "shopping", "Amazon"),
    (_r(r"NETFLIX|SPOTIFY|HULU|APPLE\.COM/BILL|YOUTUBE"), "subscriptions", None),
    (_r(r"\bSHELL\b|CHEVRON|EXXON|\b76\b|\bARCO\b"), "transport", None),
    (_r(r"UNITED AIR|DELTA AIR|ALASKA AIR|SOUTHWEST AIR|MARRIOTT|HILTON|AIRBNB"), "travel", None),
]

# The built-ins that leave a row for Review with its app as the merchant (a Zelle, Venmo, Cash App or PayPal payment
# says nothing about what it was for). The catch-up never asks these and Review's reason is "p2p" (phase 12).
P2P_MERCHANTS: tuple[str, ...] = tuple(m for _, cat, m in BUILTIN if cat == "uncategorized" and m)


NO_MATCH = Suggestion(None, "uncategorized", None, CategorySource.none)
ASKED_NO_ANSWER = Suggestion(None, "uncategorized", None, CategorySource.none, asked=True)
INLINE_ROWS = BATCH


def household_rule(db: Session, raw_description: str, amount_cents: int | None = None) -> Suggestion | None:
    """Step 1: a rule the household made, by correcting a row or by hand. A rule for this exact amount sorts the row
    when it has a category, otherwise the plain rule does (P35); a names-only rule sorts nothing, so the built-ins, the
    model and Review carry on (P34)."""
    pattern = normalize(raw_description)
    if pattern:
        rule = sorting_rule(db, pattern, amount_cents)
        if rule is not None:
            src = CategorySource.correction if rule.source == CategorySource.correction else CategorySource.rule
            return Suggestion(rule.merchant, rule.category, rule.is_business, src)
    return None


def builtin_rule(raw_description: str, amount_cents: int | None = None) -> Suggestion | None:
    """Step 2: the built-in rules. With the amount, interest a card charges (money out the Interest rule matched) is a
    Fee (phase 12 decision 10); without it the rule answers as written. The built-ins search for words, so they read
    tidy(), the fuller text: normalize() may drop the end of an ACH entry where a word they look for can sit."""
    pattern = tidy(raw_description)
    for rx, cat, merchant in BUILTIN:
        if rx.search(pattern):
            if cat == "interest" and amount_cents is not None and amount_cents < 0:
                cat = "fees"
            src = CategorySource.none if cat == "uncategorized" else CategorySource.rule
            return Suggestion(merchant, cat, None, src)
    return None


def rule_suggestion(db: Session, raw_description: str, account_type: AccountType | None = None,
                    amount_cents: int | None = None) -> Suggestion | None:
    """Steps 1 and 2 of milestone 1 5.5: the household's own rules, then the built-ins. None when neither matched.
    In an investment account a row is never left to the model: see investment_suggestion."""
    if account_type in INVESTMENT_TYPES:
        return investment_suggestion(db, raw_description)
    return household_rule(db, raw_description, amount_cents) or builtin_rule(raw_description, amount_cents)


# Investment activity out of the queue (roadmap 12). In a brokerage, retirement, HSA or 529 account, a buy, a sale, a
# reinvested dividend or a fee is the money moving inside the account: not spending, not income, and not a transfer,
# which would count as money put in (services.contributions). A dividend or interest earned there is Interest.
INVESTMENT_TYPES = frozenset({AccountType.brokerage_taxable, AccountType.k401, AccountType.roth_ira,
                              AccountType.traditional_ira, AccountType.hsa, AccountType.plan529})
INVESTMENT = "investment"
KEPT_IN_INVESTMENTS = ("transfer", "interest", "taxes")   # built-in answers that still hold inside an investment account
_EARNED = re.compile(r"\bDIV\b|DIVIDEND|\bINTEREST\b|CAP(?:ITAL)? GAIN")
_REINVEST = re.compile(r"REINVEST")


def investment_category(raw_description: str) -> str:
    """Interest for a dividend, interest or capital gain paid out; Investment activity for everything else, a
    reinvested dividend included (it's paid and bought back in the same breath)."""
    pattern = tidy(raw_description)
    return "interest" if _EARNED.search(pattern) and not _REINVEST.search(pattern) else INVESTMENT


def sort_investment_rows(db: Session, account: Account) -> int:
    """An account is an investment account now: its rows that no person or transfer sorted take investment_suggestion's
    answer (rows a person sorted, transfers and rows already Interest or Taxes stay). An account that isn't one any
    more gets the Investment activity a rule gave back as Not sorted yet, so Review shows it. Returns rows changed."""
    if account.type not in INVESTMENT_TYPES:
        back = db.execute(update(Transaction).where(
            Transaction.account_id == account.id, Transaction.category == INVESTMENT,
            Transaction.category_source == CategorySource.rule,
        ).values(category="uncategorized", category_source=CategorySource.none))
        db.flush()
        return back.rowcount or 0
    rows = db.scalars(select(Transaction).where(
        Transaction.account_id == account.id, Transaction.is_transfer.is_(False),
        Transaction.category_source != CategorySource.correction,
        Transaction.category.not_in(KEPT_IN_INVESTMENTS + (INVESTMENT,))))
    changed = 0
    for t in rows:
        s = investment_suggestion(db, t.raw_description)
        if s.category != t.category:
            t.category, t.category_source, t.merchant = s.category, s.source, s.merchant or t.merchant
            t.is_transfer = s.category == "transfer"
            t.guess_category = t.guess_pct = None          # a sorted row carries no guess (models.Transaction)
            changed += 1
    db.flush()
    return changed


def investment_suggestion(db: Session, raw_description: str) -> Suggestion:
    """The household's own rule first; then a built-in transfer, interest or tax rule; otherwise by the description.
    A store rule (AMZN is Amazon) never fires on a trade."""
    own = household_rule(db, raw_description)
    if own is not None:
        return own
    built = builtin_rule(raw_description)
    if built is not None and built.category in KEPT_IN_INVESTMENTS:
        return built
    return Suggestion(None, investment_category(raw_description), None, CategorySource.rule)


def suggest(db: Session, raw_description: str, amount_cents: int, account: Account,
            model: ModelClient | None) -> Suggestion:
    """Try the user's own rules, then the built-ins, then the model, then give up."""
    found = rule_suggestion(db, raw_description, account.type, amount_cents)
    if found is not None:
        return found
    if model is not None:
        hit = model.categorize(raw_description, amount_cents)
        if hit:
            return Suggestion(hit[1], hit[0], None, CategorySource.model, business_of(hit))
    return NO_MATCH


def model_suggestions(model, items: Sequence[tuple[str, int]], *, inline: int = INLINE_ROWS,
                      examples: Sequence[tuple[str, str]] = ()) -> list[Suggestion | None]:
    """Step 3 for rows no rule matched: at most `inline` rows are asked now, in batches of 50 (ruling 21), with the
    household's examples along (decision 3). Every row of a batch that came back is `asked` (ruling 14): sorted, left
    with a guess, or left as the model couldn't tell. Rows left unasked, or in a batch that failed, stay None and the
    client's `missed` flag sends the catch-up after them."""
    out: list[Suggestion | None] = [None] * len(items)
    if model is None or not items:
        return out
    batch = getattr(model, "categorize_batch", None)
    asked = items[:inline]
    for start in range(0, len(asked), BATCH):
        chunk = list(asked[start:start + BATCH])
        hits = batch(chunk, examples) if batch is not None else [model.categorize(d, a) for d, a in chunk]
        if hits is None:
            break
        for i, hit in enumerate(hits):
            if hit is None and batch is None:
                continue        # per row, None is a failed or cooling-down call, not an answer: not asked
            if hit:
                out[start + i] = Suggestion(hit[1], hit[0], None, CategorySource.model, business_of(hit), asked=True)
            elif isinstance(hit, Guess):
                out[start + i] = Suggestion(None, "uncategorized", None, CategorySource.none,
                                            guess=hit.category, guess_pct=hit.pct, asked=True)
            else:
                out[start + i] = ASKED_NO_ANSWER
    if len(items) > inline and hasattr(model, "missed"):
        model.missed = True
    return out
