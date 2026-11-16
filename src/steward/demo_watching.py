"""Margaret Ellis's flags (spec 11; docs/design/watching/README.md "Margaret's flags"). Run after seed_parent on the
same book. It adds the transactions behind each flag, marks everything older than 60 days as already checked, then
replays the real morning run for each of the last 60 days, so the checks themselves raise the flags on the day they
would have. Then it marks the Done ones and the Still checking one as the mockup shows. Dates are relative to today;
with Mon Oct 19, 2026 the figures match the README, and the flags are the same on any other day. Fictional throughout."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from steward.db.models import Account, CategorySource, Flag, InventoryItem, Transaction
from steward import clock
from steward.inventory.changes import record
from steward.watch.due import latest_due
from steward.watch.flags import mark_checking, mark_expected, mark_handled
from steward.watch.run import run_daily

# (days before today, account, cents, bank text, merchant, category)
TXNS = [
    (140, "Joint checking", -1999, "CVS/PHARMACY #04411 BREA CA", None, "personal"),
    (110, "Joint checking", -3380, "CVS/PHARMACY #04411 BREA CA", None, "personal"),
    (80, "Citi card", -1410, "CVS/PHARMACY #04411 BREA CA", None, "personal"),
    (51, "Citi card", -820, "CVS/PHARMACY #04411 BREA CA", None, "personal"),
    (35, "Joint checking", -6135, "CVS/PHARMACY #04411 BREA CA", None, "personal"),
    (17, "Joint checking", -2347, "CVS/PHARMACY #04411 BREA CA", None, "personal"),
    (2, "Joint checking", -50_000, "CVS/PHARMACY #09812 GIFT CARD FULLERTON CA", None, "shopping"),
    (3, "Joint checking", -120_000, "ZELLE PAYMENT TO J. SMITH CONF# QX81234", None, "uncategorized"),
    (95, "Citi card", -5210, "RALPHS #0214 FULLERTON CA", None, "groceries"),
    (70, "Citi card", -4785, "RALPHS #0214 FULLERTON CA", None, "groceries"),
    (6, "Citi card", -6418, "RALPHS #0214 FULLERTON CA", None, "groceries"),
    (5, "Citi card", -6418, "RALPHS #0214 FULLERTON CA", None, "groceries"),
    (31, "Citi card", -1599, "STREAMBOX *MONTHLY", "StreamBox", "subscriptions"),
    (1, "Citi card", -1599, "STREAMBOX *MONTHLY", "StreamBox", "subscriptions"),
    (77, "Citi card", -999, "DAILYPUZZLECLUB.COM", "Daily Puzzle Club", "subscriptions"),
    (46, "Citi card", -999, "DAILYPUZZLECLUB.COM", "Daily Puzzle Club", "subscriptions"),
    (11, "Joint checking", -64_000, "BREA FAMILY DENTAL", None, "health"),
]
NOTES = {
    "dentist": "Margaret's crown. Margaret told me about it on Sunday.",
    "clearpath": "Called Clearpath. They're refunding the second charge.",
    "puzzle": "Margaret didn't want it. We cancelled it together on the phone.",
    "ralphs": "Asked Margaret about two trips to Ralphs. Waiting to hear back.",
}


def _at(day: date, hour: int, minute: int) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=clock.household_tz())


def seed_watching(db: Session, today: date, *, by: int) -> dict[str, int]:
    accounts = {a.name: a for a in db.scalars(select(Account))}
    items = {i.name: i for i in db.scalars(select(InventoryItem))}
    for days, acct, cents, raw, merchant, category in TXNS:
        db.add(Transaction(account_id=accounts[acct].id, posted_at=today - timedelta(days=days), amount_cents=cents,
                           raw_description=raw, merchant=merchant, category=category,
                           category_source=CategorySource.rule))
    # Clearpath is "Clearpath Rx" in Transactions, and last month's premium was charged twice.
    clear = list(db.scalars(select(Transaction).where(Transaction.raw_description.like("CLEARPATH%"))
                            .order_by(Transaction.posted_at)))
    for t in clear:
        t.merchant = "Clearpath Rx"
    twice = [t for t in clear if today - timedelta(days=58) <= t.posted_at <= today - timedelta(days=14)][-1]
    db.add(Transaction(account_id=twice.account_id, posted_at=twice.posted_at + timedelta(days=1),
                       amount_cents=twice.amount_cents, raw_description=twice.raw_description, merchant="Clearpath Rx",
                       category=twice.category, category_source=CategorySource.rule))
    # The long-term care premium for the latest due date never left (README flag 39).
    nominal, _ = latest_due(10, today)
    for t in db.scalars(select(Transaction).where(Transaction.raw_description.like("EVERGREEN%"),
                                                  Transaction.posted_at >= nominal - timedelta(days=10))).all():
        db.delete(t)
    ctx = SimpleNamespace(book=SimpleNamespace(kind="parent"), user_id=by)
    for name, cents in (("Joint checking", 200_000), ("Way2Save savings", 2_500_000)):
        item = items[name]
        d = json.loads(item.details)
        d["floor_cents"] = cents
        item.details = json.dumps(d)
        record(db, ctx, "watch.floor", target_id=item.id, item_id=item.id, before={"floor_cents": None},
               after={"floor_cents": cents})
    db.flush()
    db.execute(update(Transaction).where(Transaction.posted_at < today - timedelta(days=60))
               .values(watched_at=_at(today - timedelta(days=60), 6, 12)))
    # The Globe Mutual premium is paid on the 15th or the next business day, so on some days the last two payments
    # look a few days further apart and would raise a New monthly charge flag the mockup doesn't have. Those rows
    # count as already checked, so Margaret's flags are the same whatever day this runs.
    db.execute(update(Transaction).where(Transaction.raw_description.like("GLOBE MUTUAL%"))
               .values(watched_at=_at(today - timedelta(days=60), 6, 12)))
    for n in range(60, -1, -1):
        day = today - timedelta(days=n)
        run_daily(db, day, _at(day, 6, 12))
    out = {}
    by_txn = {t: f for t, f in ((f.transaction_id, f) for f in db.scalars(select(Flag))) if t is not None}
    raw_of = {t.id: (t.raw_description, t.posted_at) for t in db.scalars(select(Transaction).where(Transaction.id.in_(by_txn)))}

    def find(prefix: str, days: int) -> int:
        return next(f.id for t, f in by_txn.items()
                    if raw_of[t][0].startswith(prefix) and raw_of[t][1] == today - timedelta(days=days))
    out["gift"] = find("CVS/PHARMACY #09812", 2)
    out["premium"] = db.scalar(select(Flag.id).where(Flag.check == "premium"))
    out["zelle"] = find("ZELLE PAYMENT TO J. SMITH", 3)
    out["low"] = db.scalar(select(Flag.id).where(Flag.check == "low"))
    out["streambox"] = find("STREAMBOX", 1)
    out["ralphs"] = find("RALPHS", 5)
    out["dentist"] = find("BREA FAMILY DENTAL", 11)
    out["clearpath"] = find("CLEARPATH", (today - twice.posted_at).days - 1)
    out["puzzle"] = find("DAILYPUZZLECLUB", 46)
    flag = {k: db.get(Flag, v) for k, v in out.items()}
    mark_expected(db, ctx, flag["dentist"], {"scope": "about", "note": NOTES["dentist"]}, _at(today - timedelta(days=10), 12, 15))
    mark_handled(db, ctx, flag["clearpath"], {"note": NOTES["clearpath"]}, _at(twice.posted_at + timedelta(days=4), 17, 31))
    mark_handled(db, ctx, flag["puzzle"], {"note": NOTES["puzzle"]}, _at(today - timedelta(days=43), 20, 10))
    mark_checking(db, ctx, flag["ralphs"], {"note": NOTES["ralphs"]}, _at(today - timedelta(days=4), 19, 40))
    db.commit()
    return out
