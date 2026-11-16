from datetime import datetime

from sqlalchemy import ColumnElement, and_, delete, func, or_, select
from sqlalchemy.orm import Session, aliased

from steward.db.models import DuplicateKeep, Transaction
from steward.services.transactions import tidy

WINDOW_DAYS = 2


def waiting_filter(at: datetime) -> ColumnElement[bool]:
    """What waits in Review at `at`: uncategorized, not a transfer, not reviewed, and not snoozed past `at`."""
    return and_(Transaction.category == "uncategorized", Transaction.is_transfer.is_(False),
                Transaction.reviewed_at.is_(None),
                or_(Transaction.snoozed_until.is_(None), Transaction.snoozed_until <= at))


def duplicate_pairs(db: Session, limit: int = 50) -> list[tuple[Transaction, Transaction]]:
    """Likely double entries: same account and amount, within 2 days, same normalized description,
    and at least one side without a bank id (two bank ids are two real purchases). Pairs the household
    kept are skipped. Ordered oldest first; a.id < b.id."""
    a, b = aliased(Transaction), aliased(Transaction)
    kept = select(DuplicateKeep.a_id, DuplicateKeep.b_id).where(DuplicateKeep.a_id == a.id, DuplicateKeep.b_id == b.id)
    stmt = (
        select(a, b)
        .join(b, and_(b.account_id == a.account_id, b.amount_cents == a.amount_cents, b.id > a.id,
                      func.abs(func.julianday(b.posted_at) - func.julianday(a.posted_at)) <= WINDOW_DAYS))
        .where(or_(a.external_id.is_(None), b.external_id.is_(None)), ~kept.exists())
        .order_by(a.posted_at, a.id, b.id)
    )
    out = []
    for x, y in db.execute(stmt):
        if tidy(x.raw_description) == tidy(y.raw_description):
            out.append((x, y))
            if len(out) >= limit:
                break
    return out


def forget_duplicate_keeps(db: Session, ids: list[int]) -> None:
    """Drop keep-both records that mention any of these transactions (call before deleting them)."""
    if ids:
        db.execute(delete(DuplicateKeep).where(or_(DuplicateKeep.a_id.in_(ids), DuplicateKeep.b_id.in_(ids))))
