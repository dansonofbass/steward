"""The watcher's settings and marks (watch_state), known payees as check rules, and raising a flag (spec 4.1)."""
from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import DuplicateKeep, Flag, FlagEvent, MailOutbox, WatchKnown, WatchState
from steward.watch import vocab as V
from steward.watch.checks import Known

LARGE = "large_cents"            # the book's Large amount, in cents (spec 4.1: per book)
CASH_FLOOR = "cash_alert_floor_cents"   # the smallest cash withdrawal that alerts when the usual monthly cash is $0
LAST_RUN = "last_run"            # JSON {at, after, transactions, accounts}
DAILY_ON = "daily_on"            # the household day of the last morning run
SUMMARY_ON = "summary_on"        # the household day of the last summary
FEED_ACCOUNTS = "feed_accounts"  # JSON list of bank feed account ids already seen (ruling 13)


def get_state(db: Session, key: str) -> str | None:
    row = db.get(WatchState, key)
    return row.value if row is not None else None


def set_state(db: Session, key: str, value: str | None, now: datetime) -> None:
    row = db.get(WatchState, key)
    if value is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(WatchState(key=key, value=value, updated_at=now))
    else:
        row.value, row.updated_at = value, now
    db.flush()


def large_cents(db: Session) -> int:
    value = get_state(db, LARGE)
    return int(value) if value else V.DEFAULT_LARGE_CENTS


def cash_floor_cents(db: Session) -> int:
    value = get_state(db, CASH_FLOOR)
    return int(value) if value else V.DEFAULT_CASH_FLOOR_CENTS


def active_known(db: Session) -> list[WatchKnown]:
    return list(db.scalars(select(WatchKnown).where(WatchKnown.removed_at.is_(None))
                           .order_by(WatchKnown.added_at.desc(), WatchKnown.id.desc())))


def known_rules(db: Session) -> tuple[Known, ...]:
    return tuple(Known(k.payee_key, k.low_cents, k.high_cents) for k in active_known(db))


def kept_pairs(db: Session) -> frozenset[tuple[int, int]]:
    return frozenset((a, b) for a, b in db.execute(select(DuplicateKeep.a_id, DuplicateKeep.b_id)))


def add_event(db: Session, flag_id: int, kind: str, now: datetime, *, user_ids: Iterable[int] | None = None,
              detail: dict | None = None) -> FlagEvent:
    e = FlagEvent(flag_id=flag_id, kind=kind, at=now, detail=json.dumps(detail or {}),
                  user_ids=json.dumps(sorted(user_ids)) if user_ids is not None else None)
    db.add(e)
    db.flush()
    return e


def add_flag(db: Session, *, check: str, severity: str, summary: str, title: str, facts: dict, now: datetime,
             after: str, also: Iterable[dict] = (), transaction_id: int | None = None, item_id: int | None = None,
             account_id: int | None = None, due_on: date | None = None) -> Flag:
    """A new open flag with its "flagged" History line; an urgent one also queues its email (spec 4.3)."""
    f = Flag(check=check, severity=severity, status="open", summary=summary, title=title, facts=json.dumps(facts),
             also=json.dumps(list(also)), transaction_id=transaction_id, item_id=item_id, account_id=account_id,
             due_on=due_on, created_at=now)
    db.add(f)
    db.flush()
    add_event(db, f.id, "flagged", now, detail={"after": after})
    if severity == "urgent":
        db.add(MailOutbox(kind="urgent", flag_id=f.id, flag_ids=json.dumps([f.id]), status="pending", created_at=now,
                          next_try_at=now, tries=0, sent_to="[]"))
        db.flush()
    return f


def facts_of(f: Flag) -> dict:
    return json.loads(f.facts or "{}")


def also_of(f: Flag) -> list[dict]:
    return json.loads(f.also or "[]")
