"""How an investment account is doing this year (investment views spec, The investment account page).

The window runs from Jan 1 when a balance from before Jan 1 exists (that balance is the start), else from the first
balance Steward saw (its balance is the start, and money is counted from the next day), to the latest balance. "You
put in" is the money in less the money out over the window (yours, the match and rollovers, less transfers out), plus
the pay-facts part for Person 1's 401(k), prorated by days. Market growth is the change less that. The chart's series is the
balance at each snapshot against the running total put in, from the first snapshot."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import Account, BalanceSnapshot
from steward.services.contributed import Contributed, deposits

MAX_POINTS = 200


@dataclass(frozen=True)
class YearFigures:
    start: date
    from_jan1: bool
    start_cents: int
    end_cents: int
    change_cents: int
    change_pct: float | None    # None when the start was $0 or less
    put_in_cents: int
    growth_cents: int
    estimated: bool             # part of "You put in" is estimated from the pay facts

    def out(self) -> dict:
        return {"start": self.start.isoformat(), "from_jan1": self.from_jan1, "start_cents": self.start_cents,
                "end_cents": self.end_cents, "change_cents": self.change_cents, "change_pct": self.change_pct,
                "put_in_cents": self.put_in_cents, "growth_cents": self.growth_cents, "estimated": self.estimated}


def _snapshots(db: Session, account_id: int, today: date) -> list[tuple[date, int]]:
    return [(d, c) for d, c in db.execute(
        select(BalanceSnapshot.as_of, BalanceSnapshot.balance_cents)
        .where(BalanceSnapshot.account_id == account_id, BalanceSnapshot.as_of <= today).order_by(BalanceSnapshot.as_of))]


def pay_part(c: Contributed) -> int:
    """The part of this year's money in that comes from the pay facts rather than the account's own rows."""
    return ((c.you_cents if c.you_from in ("payroll", "estimate") else 0)
            + (c.match_cents if c.match_from == "estimate" else 0))


def _prorated(amount: int, through: date, start: date, end: date) -> int:
    """`amount` ran evenly from Jan 1 of through's year to through; its share inside [start, end]."""
    if not amount:
        return 0
    jan1 = date(through.year, 1, 1)
    lo, hi = max(start, jan1), min(end, through)
    if hi < lo:
        return 0
    return round(amount * ((hi - lo).days + 1) / ((through - jan1).days + 1))


def year_figures(db: Session, account: Account, today: date, c: Contributed) -> YearFigures | None:
    snaps = _snapshots(db, account.id, today)
    jan1 = date(today.year, 1, 1)
    if not snaps or snaps[-1][0] < jan1:
        return None
    before = [s for s in snaps if s[0] < jan1]
    if before:
        start, start_cents, counted_from, from_jan1 = jan1, before[-1][1], jan1, True
    else:
        (start, start_cents), from_jan1 = snaps[0], False
        counted_from = start + timedelta(days=1)
    end, end_cents = snaps[-1]
    flows = sum(d.cents for d in deposits(db, [account.id], counted_from, end + timedelta(days=1)))
    put_in = flows + _prorated(pay_part(c), c.through, counted_from, end)
    change = end_cents - start_cents
    pct = round(change * 100 / start_cents, 1) if start_cents > 0 else None
    return YearFigures(start, from_jan1, start_cents, end_cents, change, pct, put_in, change - put_in,
                       c.estimated and pay_part(c) > 0)


def _thin(points: list, cap: int) -> list:
    """At most about `cap` evenly spaced points, always keeping the first and last."""
    if len(points) <= cap:
        return points
    step = -(-len(points) // cap)
    out = points[::step]
    if out[-1] != points[-1]:
        out.append(points[-1])
    return out


def series(db: Session, account: Account, today: date, c: Contributed) -> tuple[date | None, list[dict]]:
    snaps = _snapshots(db, account.id, today)
    if not snaps:
        return None, []
    first = snaps[0][0]
    after = first + timedelta(days=1)
    flows = deposits(db, [account.id], after, today + timedelta(days=1))
    pay = pay_part(c)
    out, i, running = [], 0, 0
    for day, bal in _thin(snaps, MAX_POINTS):
        while i < len(flows) and flows[i].day <= day:
            running += flows[i].cents
            i += 1
        out.append({"date": day.isoformat(), "balance_cents": bal,
                    "put_in_cents": running + _prorated(pay, c.through, after, day)})
    return first, out
