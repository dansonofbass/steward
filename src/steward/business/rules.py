"""Business rules (spec 5; rulings 3-4). Order, most specific first: a merchant on an account, a client (money in, any
account), a whole account, then an old merchant_rule.is_business, then a business account (business-type or owned by
"Business", final review ruling I1). A rule never changes a row a person decided (business_source "manual") or a
transfer. Patterns are normalized descriptions taken from a transaction, never typed."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.business.lines import TXN_LINES
from steward.business.tagging import set_business
from steward.db.models import BUSINESS_RULE_KINDS, Account, BusinessRule, Transaction
from steward.services.transactions import normalize


class RuleError(ValueError):
    """A rule that can't be made; the message is in plain words."""


class RuleSet:
    def __init__(self, rules: list[BusinessRule]):
        self.merchant = {(r.pattern, r.account_id): r for r in rules if r.kind == "merchant"}
        self.client = {r.pattern: r for r in rules if r.kind == "client"}
        self.account = {r.account_id: r for r in rules if r.kind == "account"}

    @classmethod
    def load(cls, db: Session) -> "RuleSet":
        return cls(list(db.scalars(select(BusinessRule).order_by(BusinessRule.id))))

    def match(self, account_id: int, pattern: str, amount_cents: int) -> BusinessRule | None:
        found = self.merchant.get((pattern, account_id))
        if found is None and amount_cents > 0:
            found = self.client.get(pattern)
        return found or self.account.get(account_id)

    def business_for(self, account_id: int, raw: str, amount_cents: int, *, legacy: bool | None,
                     owner_business: bool) -> tuple[int, str, str | None]:
        found = self.match(account_id, normalize(raw), amount_cents)
        if found is not None:
            return found.pct, "rule", found.line
        if legacy is not None:
            return (100, "rule", None) if legacy else (0, "none", None)
        if owner_business:
            return 100, "account", None
        return 0, "none", None


def _candidates(db: Session, r: BusinessRule) -> list[Transaction]:
    q = select(Transaction).where(Transaction.is_transfer.is_(False), Transaction.business_source != "manual",
                                  Transaction.reimburser_id.is_(None))      # reimbursable spec: never a reimbursable row
    if r.kind == "account":
        return list(db.scalars(q.where(Transaction.account_id == r.account_id)))
    if r.kind == "merchant":
        q = q.where(Transaction.account_id == r.account_id)
    else:
        q = q.where(Transaction.amount_cents > 0)
    return [t for t in db.scalars(q) if normalize(t.raw_description) == r.pattern]


def _retag(db: Session, r: BusinessRule) -> int:
    rules = RuleSet.load(db)
    n = 0
    for t in _candidates(db, r):
        best = rules.match(t.account_id, r.pattern or normalize(t.raw_description), t.amount_cents)
        if best is None:
            continue
        if (t.business_pct, t.business_line, t.business_source) != (best.pct, best.line, "rule"):
            set_business(t, best.pct, source="rule", line=best.line)
            n += 1
    db.flush()
    return n


def add_rule(db: Session, *, kind: str, pct: int, line: str | None, user_id: int, at: datetime,
             txn: Transaction | None = None, account: Account | None = None) -> tuple[BusinessRule, int]:
    if kind not in BUSINESS_RULE_KINDS:
        raise RuleError("Choose a merchant, a client or a whole account.")
    if kind == "client":
        pct, line = 100, "income"       # a client's payments are income at 100% (final review M2, M5)
    if isinstance(pct, bool) or not isinstance(pct, int) or not 1 <= pct <= 100:
        raise RuleError("Choose a whole percent from 1 to 100.")
    if line is not None and line not in TXN_LINES:
        raise RuleError("That isn't one of the Schedule C lines.")
    if kind == "account":
        if account is None:
            raise RuleError("Choose an account.")
        pattern, account_id, label = None, account.id, account.name
    else:
        if txn is None:
            raise RuleError("Choose a transaction to make the rule from.")
        if kind == "client" and txn.amount_cents <= 0:
            raise RuleError("A client is someone who pays you, so choose money coming in.")
        pattern = normalize(txn.raw_description)
        if not pattern:
            raise RuleError("This description has nothing a rule could match.")
        account_id = txn.account_id if kind == "merchant" else None
        label = (txn.merchant or pattern.title())[:200]
    found = db.scalar(select(BusinessRule).where(BusinessRule.kind == kind,
                                                 BusinessRule.pattern.is_(None) if pattern is None
                                                 else BusinessRule.pattern == pattern,
                                                 BusinessRule.account_id.is_(None) if account_id is None
                                                 else BusinessRule.account_id == account_id))
    if found is None:
        found = BusinessRule(kind=kind, pattern=pattern, account_id=account_id, pct=pct, line=line, label=label,
                             created_at=at, created_by=user_id)
        db.add(found)
    else:
        found.pct, found.line = pct, line
    db.flush()
    return found, _retag(db, found)


def remove_rule(db: Session, rule_id: int) -> bool:
    """Removes the rule; rows it tagged keep their tags (ruling 3)."""
    r = db.get(BusinessRule, rule_id)
    if r is None:
        return False
    db.delete(r)
    db.flush()
    return True


def rule_out(r: BusinessRule, account_names: dict[int, str]) -> dict:
    return {"id": r.id, "kind": r.kind, "label": r.label, "account_id": r.account_id,
            "account_name": account_names.get(r.account_id) if r.account_id is not None else None,
            "pct": r.pct, "line": r.line}
