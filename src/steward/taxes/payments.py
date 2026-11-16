"""Estimated tax payments found in the household's transactions (spec 7.1; ruling 6): money out, not a transfer, to
the IRS or (in California) the FTB, posted after last year's January due date up to this year's. Each counts unless
someone marked it "Not an estimate" (a balance due with last year's return, say). An EFTPS payment from a business
account starts uncounted, since an employer's payroll tax deposits look the same, until someone counts it."""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from steward.db.models import Account, AccountType, Transaction
from steward.engine.tax.estimates import last_federal_due
from steward.taxes.store import estimates, not_estimates

FEDERAL = re.compile(r"\bIRS\b|USTREAS|US TREASURY|\bEFTPS\b", re.IGNORECASE)
STATE = {"CA": re.compile(r"FRANCHISE TAX|\bFTB\b|CA TAX PAYMENT", re.IGNORECASE)}
LIKE = ("%IRS%", "%TREAS%", "%EFTPS%", "%FRANCHISE TAX%", "%FTB%", "%CA TAX PAYMENT%")
# An employer's payroll tax deposits go through EFTPS from the business account and read like this (final review m8);
# from a business account they start as not estimates, and one tap counts one that was.
DEPOSIT = re.compile(r"\bEFTPS\b|USATAXPYMT", re.IGNORECASE)
BUSINESS_TYPES = (AccountType.business_checking, AccountType.business_credit)


@dataclass(frozen=True)
class Payment:
    id: int
    posted_at: date
    agency: Literal["federal", "state"]
    amount_cents: int            # positive
    counts: bool
    description: str


def window(year: int) -> tuple[date, date]:
    """Payments for the tax year: after last year's January date, through this year's."""
    return last_federal_due(year - 1), last_federal_due(year)


def find_payments(db: Session, year: int, state: str) -> list[Payment]:
    after, through = window(year)
    marks = not_estimates(db)
    kept = estimates(db)
    state_re = STATE.get(state)
    business = {i for i, t, o in db.execute(select(Account.id, Account.type, Account.owner))
                if t in BUSINESS_TYPES or o == "business"}
    rows = db.scalars(select(Transaction).where(
        Transaction.amount_cents < 0, Transaction.is_transfer.is_(False),
        Transaction.posted_at > after, Transaction.posted_at <= through,
        or_(Transaction.category == "taxes", *[Transaction.raw_description.like(p) for p in LIKE]))
        .order_by(Transaction.posted_at, Transaction.id))
    out: list[Payment] = []
    for t in rows:
        text = f"{t.raw_description} {t.merchant or ''}"
        if FEDERAL.search(text):
            agency = "federal"
        elif state_re is not None and state_re.search(text):
            agency = "state"
        else:
            continue
        deposit = agency == "federal" and t.account_id in business and DEPOSIT.search(text) is not None
        counts = t.id in kept if deposit else t.id not in marks
        out.append(Payment(t.id, t.posted_at, agency, -t.amount_cents, counts, t.raw_description))
    return out


def counted(payments: Iterable[Payment], agency: str) -> list[tuple[date, int]]:
    return [(p.posted_at, p.amount_cents) for p in payments if p.agency == agency and p.counts]
