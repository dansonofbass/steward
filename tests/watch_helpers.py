"""Helpers for the watching tests: a parent book's accounts and transactions, dated back from Mon Oct 19, 2026."""
import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import Account, CategorySource, Flag, Institution, InventoryItem, Source, Transaction
from steward.inventory import kinds as K
from steward.services.accounts import manual_institution

TODAY = date(2026, 10, 19)
NOW = datetime(2026, 10, 19, 13, 12, tzinfo=timezone.utc)     # 6:12 AM Pacific


def d(n: int) -> date:
    return TODAY - timedelta(days=n)


def account(db: Session, name="Joint checking", type_="checking", owner="joint", feed=False,
            institution="Wells Fargo", item=True) -> Account:
    if feed:
        inst = Institution(name=institution, source=Source.simplefin, simplefin_org_id=f"test-{institution}")
        db.add(inst)
        db.flush()
    else:
        inst = manual_institution(db)
    a = Account(institution_id=inst.id, name=name, type=K.ACCOUNT_TYPE_TO_ACCOUNT[type_], owner=owner,
                source=Source.simplefin if feed else Source.manual, external_id=f"sfin:test-{name}" if feed else None)
    db.add(a)
    db.flush()
    if item:
        db.add(InventoryItem(kind="account", name=name, owner=owner, institution=institution, status="confirmed",
                             data_source="feed" if feed else "manual", account_id=a.id,
                             details=json.dumps({"type": type_})))
    db.commit()
    return a


def txn(db: Session, acct: Account, days_ago: int, cents: int, raw: str, *, merchant=None, category="uncategorized",
        watched=False) -> Transaction:
    t = Transaction(account_id=acct.id, posted_at=d(days_ago), amount_cents=cents, raw_description=raw,
                    merchant=merchant, category=category, category_source=CategorySource.rule,
                    watched_at=NOW - timedelta(days=max(days_ago, 0)) if watched else None)
    db.add(t)
    db.commit()
    return t


def history(db: Session, acct: Account, days: int = 200) -> Transaction:
    """An old deposit, already checked, that gives the book enough history for the baseline checks (ruling 2)."""
    return txn(db, acct, days, 100_000, "OPENING DEPOSIT", category="income", watched=True)


def flags(db: Session) -> list[Flag]:
    return list(db.scalars(select(Flag).order_by(Flag.id)))
