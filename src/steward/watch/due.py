"""Missing deposits and missed premiums (spec 4.1; decision 6; ruling 3). Monthly income and insurance items with a
usual day, an account and something to match are checked each morning. The due date is the usual day, moved to the
next Monday from a weekend; a payment up to EARLY_DAYS before the usual day counts; the flag comes GRACE_DAYS after the
due date. A deposit that arrives closes its flag as Arrived; a premium paid late stays open with a History line."""
from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.db.models import Account, BalanceSnapshot, Flag, FlagEvent, Institution, InventoryItem, Transaction
from steward import clock
from steward.inventory import kinds as K
from steward.inventory.present import clean_account, usd
from steward.watch import vocab as V
from steward.watch.store import add_event, add_flag, facts_of


def nominal(year: int, month: int, usual_day: int) -> date:
    return date(year, month, min(usual_day, calendar.monthrange(year, month)[1]))


def due_date(year: int, month: int, usual_day: int) -> date:
    d = nominal(year, month, usual_day)
    return d + timedelta(days=(7 - d.weekday()) % 7) if d.weekday() >= 5 else d


def latest_due(usual_day: int, today: date) -> tuple[date, date] | None:
    """The most recent (nominal, due) whose grace days have passed by `today`."""
    y, m = today.year, today.month
    for _ in range(3):
        due = due_date(y, m, usual_day)
        if due + timedelta(days=V.GRACE_DAYS) <= today:
            return nominal(y, m, usual_day), due
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return None


@dataclass(frozen=True)
class Expectation:
    item_id: int
    check: str              # "deposit" or "premium"
    name: str               # "Social Security", "Long-term care"
    label: str              # "Evergreen Mutual long-term care" for a policy, the name for income
    type_label: str         # "Long-term care"
    amount_cents: int | None
    usual_day: int
    account_id: int
    account_name: str
    match: str              # found anywhere in the bank text, any case
    feed: bool


def expectations(db: Session) -> list[Expectation]:
    items = list(db.scalars(select(InventoryItem).where(InventoryItem.status != "closed").order_by(InventoryItem.id)))
    by_id = {i.id: i for i in items}
    out = []
    for i in items:
        if i.kind not in ("income", "insurance"):
            continue
        d = json.loads(i.details or "{}")
        if d.get("frequency") != "monthly" or not d.get("usual_day"):
            continue
        via = by_id.get(d.get("lands_in_id") if i.kind == "income" else d.get("paid_from_id"))
        if via is None or via.kind != "account" or via.account_id is None:
            continue
        match = (d.get("match_text") or i.institution or "").strip().upper()
        if not match:
            continue
        key = d.get(K.TYPE_FIELD[i.kind])
        word = K.type_word(i.kind, key)
        label = f"{i.institution} {word}" if i.kind == "insurance" and i.institution and word else i.name
        out.append(Expectation(i.id, "deposit" if i.kind == "income" else "premium", i.name, label,
                               K.type_label(i.kind, key) or i.name, d.get("amount_cents"), int(d["usual_day"]),
                               via.account_id, via.name, match, via.data_source == "feed"))
    return out


def _matching(e: Expectation):
    sign = Transaction.amount_cents > 0 if e.check == "deposit" else Transaction.amount_cents < 0
    return select(Transaction).where(Transaction.account_id == e.account_id, sign,
                                     Transaction.raw_description.icontains(e.match, autoescape=True))


def find_payment(db: Session, e: Expectation, since: date, before: date | None = None) -> Transaction | None:
    q = _matching(e).where(Transaction.posted_at >= since)
    if before is not None:
        q = q.where(Transaction.posted_at < before)
    return db.scalar(q.order_by(Transaction.posted_at, Transaction.id).limit(1))


def payments(db: Session, e: Expectation, limit: int = 3) -> list[Transaction]:
    return list(db.scalars(_matching(e).order_by(Transaction.posted_at.desc(), Transaction.id.desc()).limit(limit)))


def _data_reaches(db: Session, e: Expectation, day: date) -> bool:
    """A feed account whose bank synced and which reported a balance on or after `day`, or a statement account with a transaction on or after it."""
    if e.feed:
        synced = db.scalar(select(Institution.last_sync_at).join(Account, Account.institution_id == Institution.id)
                           .where(Account.id == e.account_id))
        if synced is None or synced.astimezone(clock.household_tz()).date() < day:
            return False
        # the bank can come back while one of its accounts is dropped: that account needs a fresh balance too
        fresh = db.scalar(select(func.max(BalanceSnapshot.as_of)).where(BalanceSnapshot.account_id == e.account_id))
        return fresh is not None and fresh >= day
    latest = db.scalar(select(func.max(Transaction.posted_at)).where(Transaction.account_id == e.account_id))
    return latest is not None and latest >= day


def check_missed(db: Session, today: date, now: datetime) -> list[int]:
    made = []
    for e in expectations(db):
        found = latest_due(e.usual_day, today)
        if found is None:
            continue
        nom, due = found
        if db.scalar(select(Flag.id).where(Flag.check == e.check, Flag.item_id == e.item_id, Flag.due_on == due)):
            continue
        since = nom - timedelta(days=V.EARLY_DAYS)
        if find_payment(db, e, since) is not None or not _data_reaches(db, e, due + timedelta(days=V.GRACE_DAYS)):
            continue
        first = db.scalar(select(func.min(Transaction.posted_at)).where(Transaction.account_id == e.account_id))
        if first is None or first > since:
            continue            # no data from before the window: nothing to compare
        amount = usd(e.amount_cents) if e.amount_cents is not None else None
        name, label, kind = clean_account(e.name), clean_account(e.label), clean_account(e.type_label)
        account = clean_account(e.account_name)
        if e.check == "deposit":
            summary = f"the {name} deposit{', ' + amount + ',' if amount else ''} hasn't arrived in {account}"
            title = f"{name} deposit hasn't arrived"
        else:
            summary = f"the {label} premium hasn't left {account}"
            title = f"{kind} premium hasn't left"
        f = add_flag(db, check=e.check, severity="urgent", summary=summary, title=title, now=now, after="daily",
                     item_id=e.item_id, account_id=e.account_id, due_on=due,
                     facts={"amount_cents": e.amount_cents, "usual_day": e.usual_day, "nominal": nom.isoformat(),
                            "due": due.isoformat(), "weekend": nom.strftime("%A") if nom != due else None,
                            "account": e.account_name, "item": e.name, "label": e.label, "match": e.match,
                            "as_of": today.isoformat()})
        made.append(f.id)
    return made


def settle(db: Session, today: date, now: datetime) -> None:
    """Decision 6: an arrived deposit closes its flag; a late premium adds one History line and stays open."""
    by_item = {e.item_id: e for e in expectations(db)}
    for f in db.scalars(select(Flag).where(Flag.check.in_(("deposit", "premium")), Flag.status.in_(V.NOT_DONE))).all():
        e = by_item.get(f.item_id)
        if e is None:
            continue
        facts = facts_of(f)
        nom = date.fromisoformat(facts["nominal"])
        y, m = (nom.year + 1, 1) if nom.month == 12 else (nom.year, nom.month + 1)
        following = nominal(y, m, int(facts.get("usual_day") or e.usual_day))
        # Only a payment before the next period's window can settle this one; next month's belongs to next month.
        t = find_payment(db, e, nom - timedelta(days=V.EARLY_DAYS), before=following - timedelta(days=V.EARLY_DAYS))
        if t is None or t.posted_at > today:
            continue
        detail = {"posted_at": t.posted_at.isoformat(), "amount_cents": abs(t.amount_cents),
                  "late_days": max((t.posted_at - f.due_on).days, 0) if f.due_on else 0}
        if f.check == "deposit":
            f.status, f.resolved_at, f.resolved_by = "arrived", now, None
            add_event(db, f.id, "arrived", now, detail=detail)
        elif db.scalar(select(FlagEvent.id).where(FlagEvent.flag_id == f.id, FlagEvent.kind == "paid")) is None:
            add_event(db, f.id, "paid", now, detail=detail)
    db.flush()
