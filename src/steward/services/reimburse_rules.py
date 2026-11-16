"""'Always reimbursable' (reimbursable spec, Marking): a rule per normalized description, as merchant_rule's. It marks
new rows at ingest and the untouched matching rows now (retag). A repayment's payer is remembered the same way
(engineering choice 5), so the next deposit from the employer is sorted as Reimbursement with that payer. A rule never
changes a row a person decided (reimburse_source "manual"), a transfer or a business row. It reaches money out, and
money in only when that is a repayment."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import ReimburseRule, Reimburser, Transaction
from steward.services.reimburse import NOT_FOR_TRANSFERS, ReimburseError, payers
from steward.services.transactions import normalize
from steward.services.vault_flows import REPAYMENT

NO_PATTERN = "This description has nothing a rule could match."


def reaches(t: Transaction) -> bool:
    if t.is_transfer or t.business_pct or t.reimburse_source == "manual":
        return False
    return t.category == REPAYMENT or t.amount_cents < 0


def apply_rules(db: Session, rows: Iterable[Transaction]) -> int:
    """At ingest, and for rows a spread sorted as Reimbursement. A matching rule marks a charge; a repayment takes its
    rule's payer, else the book's only payer. Returns how many changed."""
    rules = {r.pattern: r.reimburser_id for r in db.scalars(select(ReimburseRule))}
    every = payers(db)
    only = every[0].id if len(every) == 1 else None
    n = 0
    for t in rows:
        if not reaches(t):
            continue
        rid = rules.get(normalize(t.raw_description))
        if rid is None and t.category == REPAYMENT:
            rid = only
        if rid is not None and t.reimburser_id != rid:
            t.reimburser_id, t.reimburse_source = rid, "rule"
            n += 1
    db.flush()
    return n


def retag(db: Session, rule: ReimburseRule) -> int:
    """The untouched rows with the rule's pattern take it now. The SQL narrows by the pattern's first word; the exact
    test is normalize()."""
    first = rule.pattern.split(" ")[0]
    rows = db.scalars(select(Transaction).where(Transaction.raw_description.icontains(first, autoescape=True),
                                                Transaction.reimburse_source != "manual",
                                                Transaction.reimburser_id.is_distinct_from(rule.reimburser_id))
                      .order_by(Transaction.id))
    return apply_rules(db, [t for t in rows if normalize(t.raw_description) == rule.pattern])


def add_rule(db: Session, txn: Transaction, payer: Reimburser, at: datetime) -> tuple[ReimburseRule, int]:
    """'Always reimbursable for <description>', made from a row, or moved to another payer. Returns the rule and how
    many other rows it marked ("Also marked 3 more.")."""
    if txn.is_transfer:
        raise ReimburseError(NOT_FOR_TRANSFERS)
    pattern = normalize(txn.raw_description)
    if not pattern:
        raise ReimburseError(NO_PATTERN)
    rule = db.scalar(select(ReimburseRule).where(ReimburseRule.pattern == pattern))
    if rule is None:
        rule = ReimburseRule(pattern=pattern, reimburser_id=payer.id, created_at=at)
        db.add(rule)
    else:
        rule.reimburser_id = payer.id
    db.flush()
    return rule, retag(db, rule)


def remember_payer(db: Session, txn: Transaction, payer: Reimburser, at: datetime) -> None:
    """A deposit sorted as Reimbursement: its description remembers the payer (spec, A repayment). An unnormalizable
    description can't be remembered, and that's fine."""
    if normalize(txn.raw_description):
        add_rule(db, txn, payer, at)
