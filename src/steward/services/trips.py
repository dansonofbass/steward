"""Trips (reimbursable spec, Trips): which of the household's charges around a trip's dates were likely work. The card
is shared (decision 5), so it says nothing about who paid: each row is grouped by what its description and category
say, and by the household's home merchants. Groups, in order: booked before the trip, likely work, probably home, not
sure. Each row says why. Engineering choice 2 settles the order: booked ahead; says the city or state; a flight, a
hotel or a travel charge; a ride; a home merchant; a home-only category; never seen at home; otherwise not sure."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from steward.db.models import Account, Transaction, Trip
from steward.services.reimburse import ReimburseError, payer_for
from steward.services.transactions import normalize
from steward.services.vault_flows import CASH_FLOW_TYPES, REPAYMENT
from steward_boundary.vocab import STATES

BOOKED_DAYS = 60            # R1: flights and hotels booked up to 60 days before the start
HOME_DAYS = 183             # "the 6 months before the trip"
HOME_MONTHS = 3             # a home merchant: 3 or more distinct months of those 6
TRIP_MAX_DAYS = 90
NAME_MAX, CITY_MAX = 80, 60
AIR = frozenset({"AIR", "AIRLINE", "AIRLINES", "AIRWAYS", "JETBLUE", "SOUTHWEST", "FLIGHT"})
HOTEL = frozenset({"HOTEL", "HOTELS", "INN", "MARRIOTT", "HILTON", "HYATT", "AIRBNB", "SHERATON", "WESTIN", "MOTEL",
                   "SUITES", "RESORT", "LODGE"})
RIDE = frozenset({"UBER", "LYFT", "TAXI", "CAB"})
HOME_ONLY = frozenset({"groceries", "kids", "pets", "childcare_education", "utilities", "housing", "subscriptions",
                       "insurance", "loan_payments", "home"})
GROUPS = ("booked", "likely", "home", "unsure")
TICKED = frozenset({"booked", "likely"})
_WORD = re.compile(r"[A-Z0-9]+")

TRIP_NAME = "Give the trip a name of up to 80 characters."
TRIP_DATES = "Choose the days the trip starts and ends."
TRIP_BACKWARDS = "The trip ends before it starts."
TRIP_TOO_LONG = "A trip can be at most 90 days."
CITY_RULE = "Give a city of up to 60 characters, or leave it empty."
STALE = "That list changed. Open the trip again."
NO_SUCH_TRIP = "No such trip."


@dataclass(frozen=True)
class Place:
    city: str | None        # upper case, as typed: "CHICAGO", "ST. LOUIS"
    state: str | None       # a real two-letter code: "IL"
    shown: str | None       # the city as the person typed it, for "says Chicago"


def place_of(city: str | None) -> Place:
    """'Chicago', 'Chicago, IL', or a state code alone, 'IL' (engineering choice 15)."""
    if not city or not city.strip():
        return Place(None, None, None)
    head, _, tail = city.partition(",")
    head, tail = " ".join(head.split()), tail.strip().upper()
    if not tail and head.upper() in STATES:
        return Place(None, head.upper(), None)
    return Place(head.upper() or None, tail if tail in STATES else None, head or None)


def _words(raw: str) -> list[str]:
    return _WORD.findall(raw.upper())


def says(raw: str, p: Place) -> str | None:
    """The place a description names, as whole words: the city first, then the state code."""
    words = _words(raw)
    if p.city:
        city = " ".join(_words(p.city))
        if city and f" {city} " in f" {' '.join(words)} ":
            return p.shown
    if p.state and p.state in words:
        return p.state
    return None


@dataclass(frozen=True)
class Row:
    txn: Transaction
    group: str
    reason: dict
    ticked: bool


def _home(db: Session, trip: Trip) -> tuple[set[str], set[str]]:
    """(home merchants, seen): the money-out descriptions on 3 or more distinct months of the 6 months before the trip,
    and every one seen there at all. Rows marked reimbursable, and rows inside another trip's dates, are left out."""
    others = [(o.start - timedelta(days=1), o.end + timedelta(days=1))
              for o in db.scalars(select(Trip).where(Trip.id != trip.id))]
    months: dict[str, set[tuple[int, int]]] = {}
    for raw, on in db.execute(
            select(Transaction.raw_description, Transaction.posted_at)
            .join(Account, Account.id == Transaction.account_id)
            .where(Transaction.posted_at >= trip.start - timedelta(days=HOME_DAYS),
                   Transaction.posted_at < trip.start - timedelta(days=1), Transaction.amount_cents < 0,
                   Transaction.is_transfer.is_(False), Transaction.reimburser_id.is_(None),
                   Transaction.trip_id.is_(None), Account.type.in_(CASH_FLOW_TYPES))):
        if any(a <= on <= b for a, b in others):
            continue
        pattern = normalize(raw)
        if pattern:
            months.setdefault(pattern, set()).add((on.year, on.month))
    return {p for p, m in months.items() if len(m) >= HOME_MONTHS}, set(months)


def _candidates(db: Session, trip: Trip) -> list[Transaction]:
    """The rows a trip's list may hold (engineering choice 14): personal cash accounts, from 60 days before the start to
    the day after the end; no transfer, repayment or business row; none on another trip. Every row already on this trip
    too."""
    near = and_(Transaction.posted_at >= trip.start - timedelta(days=BOOKED_DAYS),
                Transaction.posted_at <= trip.end + timedelta(days=1), Transaction.amount_cents != 0,
                Transaction.is_transfer.is_(False), Transaction.category.not_in(("transfer", REPAYMENT)),
                Transaction.business_pct == 0, Account.type.in_(CASH_FLOW_TYPES),
                or_(Transaction.trip_id.is_(None), Transaction.trip_id == trip.id))
    return list(db.scalars(select(Transaction).join(Account, Account.id == Transaction.account_id)
                           .where(or_(Transaction.trip_id == trip.id, near))
                           .order_by(Transaction.posted_at, Transaction.id)))


def _group(t: Transaction, trip: Trip, p: Place, home: set[str], seen: set[str]) -> tuple[str | None, dict]:
    words = set(_words(t.raw_description)) | set(_words(t.merchant or ""))
    air, hotel = bool(words & AIR), bool(words & HOTEL)
    if t.posted_at < trip.start:
        if air or hotel:
            return "booked", {"why": "booked"}
        if t.posted_at < trip.start - timedelta(days=1):
            return None, {}
    place = says(t.raw_description, p)
    if place:
        return "likely", {"why": "says", "place": place}
    if air:
        return "likely", {"why": "flight"}
    if hotel:
        return "likely", {"why": "hotel"}
    if t.category == "travel":
        return "likely", {"why": "travel"}
    if t.category == "transport" and words & RIDE:
        return "likely", {"why": "ride"}
    pattern = normalize(t.raw_description)
    if pattern in home:
        return "home", {"why": "regular"}
    if t.category in HOME_ONLY:
        return "home", {"why": "home_only", "category": t.category}
    if pattern not in seen:
        return "likely", {"why": "new"}
    return "unsure", {"why": "unsure"}


def _ticked(t: Transaction, trip: Trip, group: str) -> bool:
    """A row on this trip, or already reimbursable, stays ticked; one a person un-marked stays unticked; otherwise the
    group decides."""
    if t.reimburse_source == "manual" and t.reimburser_id is None:
        return False
    if t.trip_id == trip.id or t.reimburser_id is not None:
        return True
    return group in TICKED


def review(db: Session, trip: Trip) -> list[Row]:
    """The trip's review list (spec, The review list). Money in during its dates from a Likely work merchant is listed
    as a refund (R2, engineering choice 16)."""
    p = place_of(trip.city)
    home, seen = _home(db, trip)
    first, last = trip.start - timedelta(days=1), trip.end + timedelta(days=1)
    rows: list[Row] = []
    likely: set[str] = set()
    money_in: list[Transaction] = []
    for t in _candidates(db, trip):
        if t.amount_cents > 0:
            money_in.append(t)
            continue
        group, why = _group(t, trip, p, home, seen)
        if group is None:
            if t.trip_id != trip.id:
                continue
            group, why = "unsure", {"why": "unsure"}       # on the trip, outside its dates now
        if group == "likely":
            likely.add(normalize(t.raw_description))
        rows.append(Row(t, group, why, _ticked(t, trip, group)))
    for t in money_in:
        if t.trip_id == trip.id or (first <= t.posted_at <= last and normalize(t.raw_description) in likely):
            rows.append(Row(t, "likely", {"why": "refund"}, _ticked(t, trip, "likely")))
    rows.sort(key=lambda r: (GROUPS.index(r.group), r.txn.posted_at, r.txn.id))
    return rows


def _day(v: object) -> date:
    if not isinstance(v, str):
        raise ReimburseError(TRIP_DATES)
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise ReimburseError(TRIP_DATES) from None


def trip_fields(db: Session, body: dict) -> dict:
    """POST and PATCH /reimburse/trips' body: name (default "{city} trip"), start, end, city, and the payer when there
    are two or more."""
    start, end = _day(body.get("start")), _day(body.get("end"))
    if end < start:
        raise ReimburseError(TRIP_BACKWARDS)
    if (end - start).days >= TRIP_MAX_DAYS:
        raise ReimburseError(TRIP_TOO_LONG)
    city = body.get("city")
    if city is not None and not isinstance(city, str):
        raise ReimburseError(CITY_RULE)
    city = " ".join((city or "").split()) or None
    if city and len(city) > CITY_MAX:
        raise ReimburseError(CITY_RULE)
    name = body.get("name")
    if name is not None and not isinstance(name, str):
        raise ReimburseError(TRIP_NAME)
    name = " ".join((name or "").split())
    if not name and city:
        name = f"{city.split(',')[0].strip()} trip"
    if not 1 <= len(name) <= NAME_MAX:
        raise ReimburseError(TRIP_NAME)
    return {"name": name, "start": start, "end": end, "city": city,
            "reimburser_id": payer_for(db, body.get("reimburser_id")).id}
