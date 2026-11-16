"""Decision 4 of the same-account spec: a transaction from one feed copies one from another when the amount is the
same and they posted within 3 days of each other, matched one to one, so two real $5 coffees on one day stay two."""
from collections.abc import Sequence
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import FeedTxnAlias, Transaction
from steward.services.importers.base import ParsedRow

WINDOW_DAYS = 3


def pair_up(incoming: Sequence[tuple[date, int]], existing: Sequence[tuple[int, date, int]],
            days: int = WINDOW_DAYS) -> dict[int, int]:
    """Index into `incoming` → the id of the existing row it matches. Each existing row matches at most once. Incoming
    rows go oldest first; each takes the unmatched existing row of the same amount nearest in date, within `days`, the
    lower id on a tie."""
    free: dict[int, list[tuple[int, date]]] = {}
    for tid, posted, cents in existing:
        free.setdefault(cents, []).append((tid, posted))
    out: dict[int, int] = {}
    for i in sorted(range(len(incoming)), key=lambda k: (incoming[k][0], k)):
        posted, cents = incoming[i]
        pool = free.get(cents)
        if not pool:
            continue
        near = [(abs((d - posted).days), tid) for tid, d in pool if abs((d - posted).days) <= days]
        if not near:
            continue
        _, tid = min(near)
        out[i] = tid
        pool[:] = [p for p in pool if p[0] != tid]
    return out


def copies(db: Session, account_id: int, feed_id: int, rows: list[ParsedRow]) -> dict[int, int]:
    """Decision 4 for rows from `feed_id` about to go into `account_id`: index into `rows` → the transaction each
    copies. Only a row that came through another of the account's feeds can be copied (a file's rows never are,
    Engineering choice 1), and not one a copy from this same feed already matched (Engineering choice 2)."""
    if not rows:
        return {}
    lo = min(r.posted_at for r in rows) - timedelta(days=WINDOW_DAYS)
    hi = max(r.posted_at for r in rows) + timedelta(days=WINDOW_DAYS)
    taken = select(FeedTxnAlias.transaction_id).where(FeedTxnAlias.feed_id == feed_id)
    existing = [tuple(r) for r in db.execute(
        select(Transaction.id, Transaction.posted_at, Transaction.amount_cents).where(
            Transaction.account_id == account_id, Transaction.feed_id.is_not(None), Transaction.feed_id != feed_id,
            Transaction.amount_cents.in_(sorted({r.amount_cents for r in rows})),
            Transaction.posted_at >= lo, Transaction.posted_at <= hi, Transaction.id.not_in(taken)))]
    return pair_up([(r.posted_at, r.amount_cents) for r in rows], existing)


def record_aliases(db: Session, account_id: int, feed_id: int, rows: list[ParsedRow], matched: dict[int, int],
                   now: datetime) -> list[FeedTxnAlias]:
    """Each dropped copy, remembered: it is never ingested again, even outside the window."""
    made = [FeedTxnAlias(account_id=account_id, feed_id=feed_id, external_id=rows[i].external_id, transaction_id=tid,
                         created_at=now) for i, tid in sorted(matched.items())]
    db.add_all(made)
    db.flush()
    return made


def drop_copies(db: Session, account_id: int, feed_id: int, rows: list[ParsedRow],
                now: datetime) -> tuple[list[ParsedRow], int]:
    """The rows to ingest, without the copies of rows already here (aliases recorded), and how many were dropped."""
    matched = copies(db, account_id, feed_id, rows)
    if matched:
        record_aliases(db, account_id, feed_id, rows, matched, now)
    return [r for i, r in enumerate(rows) if i not in matched], len(matched)


def aliased(db: Session, account_id: int, ids: list[str]) -> set[str]:
    """Of these bank ids, the ones already dropped once as copies in this account."""
    if not ids:
        return set()
    return set(db.scalars(select(FeedTxnAlias.external_id).where(FeedTxnAlias.account_id == account_id,
                                                                 FeedTxnAlias.external_id.in_(ids))))
