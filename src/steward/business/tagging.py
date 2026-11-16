"""Business or personal on one transaction (spec 5; rulings 1-2). business_pct is the tag; is_business means 100%.
A tag never changes the category, its source, the reviewed time or any merchant rule."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.business.lines import TXN_LINES
from steward.db.models import Account, AccountType, Owner, Transaction

NOT_FOR_TRANSFERS = "A transfer moves money between your own accounts, so it isn't business or personal."
KEEP = object()
BUSINESS_ACCOUNT_TYPES = (AccountType.business_checking, AccountType.business_credit)


class TagError(ValueError):
    """A tag the transaction can't take; the message is in plain words."""


def share(amount_cents: int, pct: int) -> int:
    """The business share of an amount, half a cent rounded away from zero."""
    s = (abs(amount_cents) * pct + 50) // 100
    return s if amount_cents >= 0 else -s


def personal_share(amount_cents: int, pct: int) -> int:
    """What is left for personal money, so the two shares always add up to the amount to the cent."""
    return amount_cents - share(amount_cents, pct)


def is_business_account(account: Account, household: bool = True) -> bool:
    """A business-type account, or one owned by Business (final review ruling I1): its rows are business unless a
    person said otherwise, whoever's name is on it. Household books only (spec 5): a parent book has none."""
    return household and (account.type in BUSINESS_ACCOUNT_TYPES or account.owner == Owner.business)


def retag_account(db: Session, account: Account, household: bool = True) -> int:
    """After an account's type or owner changes: rows that nothing decided follow the account. A person's choice and a
    rule's are kept; transfers are never business."""
    if is_business_account(account, household):
        rows = db.scalars(select(Transaction).where(Transaction.account_id == account.id,
                                                    Transaction.business_source == "none",
                                                    Transaction.is_transfer.is_(False),
                                                    Transaction.reimburser_id.is_(None)))
        pct, source = 100, "account"
    else:
        rows = db.scalars(select(Transaction).where(Transaction.account_id == account.id,
                                                    Transaction.business_source == "account"))
        pct, source = 0, "rule"
    n = 0
    for t in rows:
        set_business(t, pct, source=source, line=None)
        n += 1
    db.flush()
    return n


def set_business(txn: Transaction, pct: int, *, source: str, line: str | None | object = KEEP) -> None:
    """source is "manual" for a person's choice, "rule" for a rule and "account" for a business account's default. A
    person who says Personal leaves a manual mark so no rule changes it later (ruling 2); a rule that says personal
    leaves none."""
    if isinstance(pct, bool) or not isinstance(pct, int) or not 0 <= pct <= 100:
        raise TagError("Choose a whole percent from 0 to 100.")
    if line is not KEEP and line is not None and line not in TXN_LINES:
        raise TagError("That isn't one of the Schedule C lines.")
    if pct > 0 and txn.is_transfer:
        raise TagError(NOT_FOR_TRANSFERS)
    txn.business_pct = pct
    txn.is_business = pct == 100
    if pct == 0:
        txn.business_line = None
        txn.business_source = "manual" if source == "manual" else "none"
        return
    txn.business_source = source
    if line is not KEEP:
        txn.business_line = line
