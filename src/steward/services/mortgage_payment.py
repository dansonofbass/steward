"""The mortgage's monthly payment, read from the money that went into it (profile spec P21): the newest transfer pair
into the mortgage account in the last 95 days. When the last three differ by more than $1, the newest is used and the
range is said. Nothing leaves the account's own payments to guess at; no pair, no payment."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from steward.db.models import Transaction

WINDOW_DAYS = 95
VARIED_CENTS = 100


def detected(db: Session, mortgage_id: int, today: date) -> dict | None:
    peer = aliased(Transaction)
    rows = db.execute(
        select(Transaction.posted_at, Transaction.amount_cents)
        .join(peer, peer.id == Transaction.transfer_peer_id)
        .where(peer.account_id == mortgage_id, Transaction.account_id != mortgage_id, Transaction.amount_cents < 0,
               Transaction.posted_at > today - timedelta(days=WINDOW_DAYS), Transaction.posted_at <= today)
        .order_by(Transaction.posted_at.desc(), Transaction.id.desc()).limit(3)).all()
    if not rows:
        return None
    amounts = [-cents for _, cents in rows]
    varied = len(amounts) == 3 and max(amounts) - min(amounts) > VARIED_CENTS
    return {"posted_at": rows[0][0].isoformat(), "amount_cents": amounts[0],
            "varied": {"lo": min(amounts), "hi": max(amounts)} if varied else None}
