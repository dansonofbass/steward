"""The household's category rules as a list (phase 12 decision 2), the examples the model is taught with (decision 3,
ruling 16), and spreading a correction to the rows it should have reached (decision 1, ruling 12).
Rows are counted by pattern at read time: normalize is a regex, not SQL, so every description is normalized once."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from steward.db.models import Account, CategorySource, MerchantRule, Transaction
from steward.services.categorize import INVESTMENT_TYPES
from steward.services.categorizer_client import MAX_EXAMPLES
from steward.services.reimburse_rules import apply_rules
from steward.services.transactions import normalize
from steward.services.transfers import pair_transfers
from steward.services.vault_flows import REPAYMENT

NOT_TAUGHT = ("transfer", "investment", "uncategorized", "reimbursement")   # the model can't answer these (ruling 16)


def pattern_counts(db: Session) -> Counter[str]:
    """How many rows each normalized description has."""
    return Counter(normalize(raw) for raw in db.scalars(select(Transaction.raw_description)))


def example_rules(db: Session, limit: int = MAX_EXAMPLES) -> list[tuple[str, str]]:
    """The household's own corrections, the `limit` covering the most rows, ties to the newest: (pattern, category).
    Patterns are already normalized (categorizer_client masks any digits left before sending). Amount rules and rules
    with no category are left out (P39): the model sees only the pattern; no name or note is read."""
    rules = db.scalars(select(MerchantRule).where(MerchantRule.source == CategorySource.correction,
                                                  MerchantRule.amount_cents.is_(None), MerchantRule.category.is_not(None),
                                                  MerchantRule.category.not_in(NOT_TAUGHT))).all()
    if not rules:
        return []
    counts = pattern_counts(db)
    ranked = sorted(rules, key=lambda r: (-counts[r.pattern], -r.created_at.timestamp(), -r.id))
    return [(r.pattern, r.category) for r in ranked[:limit]]


RULE_GONE = "That rule was removed, so nothing else changed."
CATEGORY_CHANGED = "This transaction's category changed since, so nothing else changed."
SPREADABLE = (CategorySource.none, CategorySource.model, CategorySource.rule)
# Ruling 12's rows: no person sorted them (source none, model or rule), not reviewed, not a transfer or part of a pair,
# not in an investment account. spread_targets adds "not already in the rule's category"; matching_counts doesn't.
REACHABLE = (Transaction.category_source.in_(SPREADABLE), Transaction.reviewed_at.is_(None),
             Transaction.is_transfer.is_(False), Transaction.transfer_peer_id.is_(None),
             Account.type.not_in(INVESTMENT_TYPES))


def spread_targets(db: Session, rule: MerchantRule) -> list[Transaction]:
    """Ruling 12: the reachable rows with the rule's pattern, not already carrying the rule's category. The SQL narrows
    by the pattern's first word; the exact test is normalize()."""
    first = rule.pattern.split(" ")[0]
    q = select(Transaction).join(Account, Account.id == Transaction.account_id).where(
        Transaction.raw_description.icontains(first, autoescape=True), *REACHABLE,
        Transaction.category != rule.category)
    if rule.amount_cents is not None:
        q = q.where(Transaction.amount_cents == rule.amount_cents)
    rows = db.scalars(q.order_by(Transaction.id))
    return [t for t in rows if normalize(t.raw_description) == rule.pattern]


def matching_counts(db: Session, rows: Iterable[Transaction]) -> dict[int, int | None]:
    """Spec, The matching count: for each row, how many *other* rows a rule for its description would reach, which is
    spread_targets' set without its category condition. None when the description normalizes to nothing: no rule
    can be made, so nothing would be remembered (choice 5). One SELECT for the page, narrowed by the patterns' first
    words; rows are grouped here, by normalize(), which is a regex and not SQL."""
    patterns = {t.id: normalize(t.raw_description) for t in rows}
    found: dict[str, set[int]] = {p: set() for p in patterns.values() if p}
    if found:
        firsts = sorted({p.split(" ")[0] for p in found})
        q = (select(Transaction.id, Transaction.raw_description).join(Account, Account.id == Transaction.account_id)
             .where(*REACHABLE, or_(*(Transaction.raw_description.icontains(f, autoescape=True) for f in firsts))))
        for tid, raw in db.execute(q):
            p = normalize(raw)
            if p in found:
                found[p].add(tid)
    return {tid: (len(found[p] - {tid}) if p else None) for tid, p in patterns.items()}


def spread(db: Session, rule: MerchantRule, now: datetime) -> list[int]:
    """Apply the rule to spread_targets: they take its category and merchant as a person's correction (decision 1). A
    row that becomes a transfer, or stops being a repayment, loses its payer; rows spread to Reimbursement take theirs
    (reimbursable spec, engineering choice 6). Returns the ids it changed, in id order (review focus P22)."""
    if rule.category is None:
        return []                    # P34: a names-only rule sorts nothing
    rows = spread_targets(db, rule)
    for t in rows:
        was = t.category
        t.category, t.merchant = rule.category, rule.merchant
        t.category_source, t.reviewed_at = CategorySource.correction, now
        t.guess_category = t.guess_pct = None
        t.is_transfer = rule.category == "transfer"
        if t.reimburser_id is not None and (t.is_transfer or was == REPAYMENT):
            t.reimburser_id = t.trip_id = None
    db.flush()
    if rule.category == "transfer":
        pair_transfers(db, [t.id for t in rows])
    if rule.category == REPAYMENT:
        apply_rules(db, rows)
    return [t.id for t in rows]


def rule_out(r: MerchantRule, rows: int) -> dict:
    """A rule as the list shows it: its amount and name, and whether it carries a note, never the note (P36)."""
    return {"id": r.id, "pattern": r.pattern, "merchant": r.merchant, "category": r.category, "rows": rows,
            "created_at": r.created_at.isoformat(), "amount_cents": r.amount_cents, "nickname": r.nickname,
            "has_note": r.note is not None}


def rules_list(db: Session) -> list[dict]:
    """Every rule with how many rows it claims, most rows first, ties to the newest (decision 2). An amount rule claims
    the rows with its pattern and amount; a plain rule, the rows with its pattern that no amount rule claims."""
    rules = db.scalars(select(MerchantRule)).all()
    by_pattern: Counter[str] = Counter()
    by_amount: Counter[tuple[str, int]] = Counter()
    if rules:
        for raw, cents in db.execute(select(Transaction.raw_description, Transaction.amount_cents)):
            p = normalize(raw)
            by_pattern[p] += 1
            by_amount[(p, cents)] += 1
    claimed: Counter[str] = Counter()
    for r in rules:
        if r.amount_cents is not None:
            claimed[r.pattern] += by_amount[(r.pattern, r.amount_cents)]
    counts = {r.id: by_amount[(r.pattern, r.amount_cents)] if r.amount_cents is not None
              else by_pattern[r.pattern] - claimed[r.pattern] for r in rules}
    ranked = sorted(rules, key=lambda r: (-counts[r.id], -r.created_at.timestamp(), -r.id))
    return [rule_out(r, counts[r.id]) for r in ranked]
