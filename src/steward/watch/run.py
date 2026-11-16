"""Running the checks over a book (spec 4.1): after every sync and import, and each morning (tick.py). Only
transactions not checked before are looked at, so a changed threshold affects new transactions only. Transactions
older than STALE_DAYS are marked checked without flags (ruling 2)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from steward.db.models import Account, Flag, InventoryItem, Transaction
from steward.watch import vocab as V
from steward.watch.balances import check_low, check_new_accounts
from steward.watch.checks import History, Rules, Txn, check, primary
from steward.watch.due import check_missed, settle
from steward.watch.store import LAST_RUN, add_flag, kept_pairs, known_rules, large_cents, set_state
from steward.watch.store import cash_floor_cents

WATCH_FAILED = {
    "sync": "Couldn't run the checks after this sync.",
    "import": "Couldn't run the checks after this import.",
    "daily": "Couldn't run the morning checks.",
}


@dataclass
class RunResult:
    checked: int = 0
    accounts: int = 0
    flags: list[int] = field(default_factory=list)


def _load(db: Session) -> tuple[list[Txn], set[int]]:
    rows = db.execute(select(Transaction.id, Transaction.account_id, Transaction.posted_at, Transaction.amount_cents,
                             Transaction.raw_description, Transaction.merchant, Transaction.category,
                             Transaction.is_transfer, Transaction.transfer_peer_id, Transaction.watched_at)).all()
    txns = [Txn(r[0], r[1], r[2], r[3], r[4], r[5], r[6], bool(r[7]), r[8] is not None) for r in rows]
    return txns, {r[0] for r in rows if r[9] is None}


def _mark(db: Session, ids: list[int], now: datetime) -> None:
    for i in range(0, len(ids), 500):
        db.execute(update(Transaction).where(Transaction.id.in_(ids[i:i + 500])).values(watched_at=now))


def check_new(db: Session, today: date, now: datetime, *, after: str, max_age_days: int = V.STALE_DAYS) -> RunResult:
    txns, unwatched = _load(db)
    due = [t for t in txns if t.id in unwatched and t.posted_at <= today]
    cut = today - timedelta(days=max_age_days)
    fresh = [t for t in due if t.posted_at >= cut]
    out = RunResult(checked=len(fresh), accounts=len({t.account_id for t in fresh}))
    if fresh:
        history = History(txns)
        rules = Rules(large_cents(db), cash_floor_cents(db), known_rules(db), kept_pairs(db))
        flagged = set(db.scalars(select(Flag.transaction_id).where(Flag.transaction_id.is_not(None))))
        names = dict(db.execute(select(Account.id, Account.name)).all())
        items = dict(db.execute(select(InventoryItem.account_id, InventoryItem.id)
                                .where(InventoryItem.account_id.is_not(None))).all())
        for t in fresh:
            if t.id in flagged:
                continue
            hits = check(history, t, rules)
            if not hits:
                continue
            main, also = primary(hits)
            facts = {**main.facts, "posted_at": t.posted_at.isoformat(), "raw": t.raw,
                     "account": names.get(t.account_id, ""), "category": t.category}
            f = add_flag(db, check=main.check, severity=main.severity, summary=main.summary, title=main.title,
                         facts=facts, now=now, after=after, also=[{"check": h.check, "detail": h.detail} for h in also],
                         transaction_id=t.id, item_id=items.get(t.account_id), account_id=t.account_id)
            out.flags.append(f.id)
    _mark(db, [t.id for t in due], now)
    db.flush()
    return out


def run_watch(db: Session, today: date, now: datetime, *, after: str, max_age_days: int = V.STALE_DAYS) -> RunResult:
    """Everything a sync, an import or the morning run checks. `after` is "sync", "import" or "daily"."""
    out = check_new(db, today, now, after=after, max_age_days=max_age_days)
    out.flags += check_new_accounts(db, now, after=after)
    out.flags += check_low(db, today, now, after=after)
    settle(db, today, now)
    set_state(db, LAST_RUN, json.dumps({"at": now.isoformat(), "after": after, "transactions": out.checked,
                                        "accounts": out.accounts}), now)
    return out


def run_daily(db: Session, today: date, now: datetime) -> RunResult:
    """The morning run (ruling 17): everything a sync checks, then missed deposits and premiums."""
    out = run_watch(db, today, now, after="daily")
    out.flags += check_missed(db, today, now)
    return out


def watch_after(db: Session, after: str) -> RunResult:
    from steward import deps
    return run_watch(db, deps.today(), deps.now(), after=after)
