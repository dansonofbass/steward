"""Month by month (spec 4.4; ruling 14). Recent months' money in and out by category from the same query as Cash
flow, with transfers left out whether paired or only categorized as one, as in Care's spending (final review I2);
what the regular charges and deposits watching already knows bring in the next 60 days (inventory income and
premiums with a usual day or a renewal date, and known payees marked from a "monthly" flag, at their last amount a
month on); and a short line when, month by month, out exceeds in plus the cash on hand above the floors of checking
and savings (a CD's money isn't on hand; final review M2).
A premium paid from an income item (Medicare Part B from Social Security) never leaves the bank, so it is skipped."""
from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.care.costs import dollars
from steward.db.models import InventoryItem, Transaction
from steward.inventory import kinds as K
from steward.services.cashflow import cashflow
from steward.services.vault_flows import month_add
from steward.watch.balances import balance_on, floored_items
from steward.watch.due import nominal
from steward.watch.payees import payee
from steward.watch.store import active_known

RECENT_MONTHS = 6
AHEAD_DAYS = 60
KNOWN_LOOKBACK_DAYS = 62
CASH_ON_HAND = frozenset({"checking", "savings"})


@dataclass(frozen=True)
class Expected:
    on: date
    label: str
    cents: int              # money in positive, money out negative
    source: str             # "item" or "known"


@dataclass(frozen=True)
class Monthly:
    months: list[dict]                  # cashflow() rows, oldest first; the last is this month so far
    expected: tuple[Expected, ...]
    expected_in_cents: int
    expected_out_cents: int             # positive
    cash_cents: int
    floors_cents: int
    above_floor_cents: int
    short_month: date | None            # the first of the month that comes up short
    short_cents: int
    short_line: str | None
    undated: int                        # repeating income or premiums with no date to place them


def occurrences(anchor: date, every_months: int, start: date, end: date) -> list[date]:
    """anchor, anchor + every_months months, … (the day clipped to the month's end), from start to end inclusive."""
    lead = ((start.year - anchor.year) * 12 + start.month - anchor.month) // every_months - 1
    out, k = [], lead
    while True:
        m = month_add(anchor.replace(day=1), k * every_months)
        d = nominal(m.year, m.month, anchor.day)
        if d > end:
            return out
        if d >= start:
            out.append(d)
        k += 1


def _from_items(db: Session, start: date, end: date) -> tuple[list[Expected], int, list[str]]:
    items = list(db.scalars(select(InventoryItem).where(InventoryItem.kind.in_(("income", "insurance")),
                                                        InventoryItem.status != "closed").order_by(InventoryItem.id)))
    by_id = {i.id: i for i in items}
    out, undated, matches = [], 0, []
    for i in items:
        d = json.loads(i.details or "{}")
        amount, freq = d.get("amount_cents"), d.get("frequency")
        if not amount or freq not in K.FREQUENCIES:
            continue
        if i.kind == "insurance" and getattr(by_id.get(d.get("paid_from_id")), "kind", None) == "income":
            continue
        if freq == "monthly" and d.get("usual_day"):
            anchor = nominal(start.year, start.month, int(d["usual_day"]))
        elif i.kind == "insurance" and d.get("renewal_on"):
            anchor = date.fromisoformat(d["renewal_on"])
        else:
            undated += 1
            continue
        sign = 1 if i.kind == "income" else -1
        out += [Expected(on, i.name, sign * amount, "item") for on in occurrences(anchor, K.FREQUENCIES[freq], start, end)]
        match = (d.get("match_text") or i.institution or "").strip().upper()
        if match:
            matches.append(match)
    return out, undated, matches


def _from_known(db: Session, today: date, start: date, end: date, item_matches: list[str]) -> list[Expected]:
    known = [k for k in active_known(db) if k.check == "monthly"]
    if not known:
        return []
    rows = db.execute(select(Transaction.posted_at, Transaction.amount_cents, Transaction.raw_description,
                             Transaction.merchant)
                      .where(Transaction.posted_at > today - timedelta(days=KNOWN_LOOKBACK_DAYS),
                             Transaction.posted_at <= today, Transaction.amount_cents < 0,
                             Transaction.is_transfer.is_(False), Transaction.category != "transfer")
                      .order_by(Transaction.posted_at.desc(), Transaction.id.desc())).all()
    last: dict[str, tuple[date, int]] = {}
    for posted, cents, raw, merchant in rows:
        if any(m in raw.upper() for m in item_matches):
            continue                    # an inventory premium already lists it
        key = payee(raw, merchant).key
        if key and key not in last:
            last[key] = (posted, cents)
    out = []
    for k in known:
        if k.payee_key in last:
            posted, cents = last[k.payee_key]
            out += [Expected(on, k.payee_name, cents, "known") for on in occurrences(posted, 1, start, end)]
    return out


def month_by_month(db: Session, today: date) -> Monthly:
    start, end = today + timedelta(days=1), today + timedelta(days=AHEAD_DAYS)
    items, undated, matches = _from_items(db, start, end)
    expected = tuple(sorted(items + _from_known(db, today, start, end, matches), key=lambda e: (e.on, -e.cents, e.label)))
    cash = floors = 0
    for item, d in floored_items(db):
        if d.get("type") not in CASH_ON_HAND:
            continue                    # a CD's money is locked in until it matures (final review M2)
        bal = balance_on(db, item.account_id, today)
        cash += bal[1] if bal else 0
        floors += d.get("floor_cents") or 0
    available, short_month, short = cash - floors, None, 0
    month = today.replace(day=1)
    while month <= end:
        nxt = month_add(month, 1)
        available += sum(e.cents for e in expected if month <= e.on < nxt)
        if available < 0:
            short_month, short = month, -available
            break
        month = nxt
    line = None
    if short_month is not None:
        line = (f"Short this month by {dollars(short)}" if short_month == today.replace(day=1)
                else f"Short in {calendar.month_name[short_month.month]} by {dollars(short)}")
    return Monthly(months=cashflow(db, today, RECENT_MONTHS, leave_out_transfers=True), expected=expected,
                   expected_in_cents=sum(e.cents for e in expected if e.cents > 0),
                   expected_out_cents=-sum(e.cents for e in expected if e.cents < 0),
                   cash_cents=cash, floors_cents=floors, above_floor_cents=cash - floors, short_month=short_month,
                   short_cents=short, short_line=line, undated=undated)
