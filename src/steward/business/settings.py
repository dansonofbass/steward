"""The household's business settings, kept in business_state (ruling 12). Keys: type, home_office:<year> (JSON),
car_method:<year>, miles:<year> (JSON list, one count per rate period), expect:<year> (JSON {low_cents, high_cents},
the rest of the year's profit before the home office), s_corp (JSON {salary_pct, cost_cents}), owner (jr or spouse:
who runs the business, one value for every year; final review ruling I2).

The home office and the car are kept per tax year (final review ruling I2), so last year can be finished and this
year's choices never rewrite it. A year with no entry of its own reads the latest earlier year's. Changing a year first
copies what each later year up to this year was showing into that year, so a later year never changes underneath."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import BusinessState

TYPES = ("none", "sole_prop", "s_corp")
HOME_OFFICE_METHODS = ("none", "simplified", "actual")
CAR_METHODS = ("standard", "actual")
MAX_SQFT = 100_000
MAX_HOME_COSTS = 1_000_000_000      # $10,000,000 a year
MAX_PROFIT = 1_000_000_000          # $10,000,000 either way
MAX_MILES = 200_000
MAX_SCORP_COST = 10_000_000         # $100,000 a year
OWNERS = ("jr", "spouse")
UNDERSTOOD = frozenset({"type", "home_office", "car_method", "miles", "expect", "s_corp", "owner", "year"})
YEARLY = ("home_office", "car_method")


class SettingsError(ValueError):
    """A value the settings can't take; the message is in plain words."""


@dataclass(frozen=True)
class HomeOffice:
    method: str = "none"
    office_sqft: int = 0
    home_sqft: int = 0
    home_costs_cents: int = 0


@dataclass(frozen=True)
class Expect:
    low_cents: int
    high_cents: int


@dataclass(frozen=True)
class SCorp:
    salary_pct: int = 50
    cost_cents: int = 150_000


@dataclass(frozen=True)
class BusinessSettings:
    type: str
    home_office: HomeOffice
    car_method: str
    s_corp: SCorp
    owner: str = "jr"


def _get(db: Session, key: str) -> str | None:
    row = db.get(BusinessState, key)
    return row.value if row is not None else None


def _put(db: Session, key: str, value: str | None, user_id: int, at: datetime) -> None:
    row = db.get(BusinessState, key)
    if value is None:
        if row is not None:
            db.delete(row)
        return
    if row is None:
        db.add(BusinessState(key=key, value=value, updated_at=at, updated_by=user_id))
    else:
        row.value, row.updated_at, row.updated_by = value, at, user_id


def business_type(db: Session) -> str:
    return _get(db, "type") or "none"


def business_owner(db: Session) -> str:
    """Who runs the business: "jr" (the first adult, the default) or "spouse". Callers with a single filer read
    "spouse" as the one adult on the return (owner_index)."""
    v = _get(db, "owner")
    return v if v in OWNERS else "jr"


def owner_index(db: Session, adults: int) -> int:
    """The business owner as an index into the return's adults (0 or 1), the first when there is only one."""
    return 1 if business_owner(db) == "spouse" and adults > 1 else 0


def _own_years(db: Session, name: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for key, value in db.execute(select(BusinessState.key, BusinessState.value)
                                 .where(BusinessState.key.like(f"{name}:%"))):
        suffix = key[len(name) + 1:]
        if suffix.isascii() and suffix.isdigit():
            out[int(suffix)] = value
    return out


def _yearly(db: Session, name: str, year: int) -> str | None:
    """The year's own value, else the latest earlier year's; None when no year up to this one has one."""
    have = _own_years(db, name)
    earlier = [y for y in have if y <= year]
    return have[max(earlier)] if earlier else None


def read_settings(db: Session, year: int) -> BusinessSettings:
    ho = _yearly(db, "home_office", year)
    sc = _get(db, "s_corp")
    return BusinessSettings(type=business_type(db), home_office=HomeOffice(**json.loads(ho)) if ho else HomeOffice(),
                            car_method=_yearly(db, "car_method", year) or "standard",
                            s_corp=SCorp(**json.loads(sc)) if sc else SCorp(), owner=business_owner(db))


def miles_for(db: Session, year: int, periods: int) -> tuple[int, ...]:
    raw = _get(db, f"miles:{year}")
    have = list(json.loads(raw)) if raw else []
    return tuple((have + [0] * periods)[:periods])


def expect_for(db: Session, year: int) -> Expect | None:
    raw = _get(db, f"expect:{year}")
    return Expect(**json.loads(raw)) if raw else None


def _whole(v, lo: int, hi: int, message: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise SettingsError(message)
    return v


def _object(v) -> dict:
    if not isinstance(v, dict):
        raise SettingsError("That request wasn't understood.")
    return v


def update_settings(db: Session, body: dict, *, year: int, this_year: int, periods: int, user_id: int,
                    at: datetime) -> None:
    """Checks every value first, then writes; nothing is written when any value is refused."""
    if set(body) - UNDERSTOOD:
        raise SettingsError("That request wasn't understood.")
    writes: dict[str, str | None] = {}
    if "type" in body:
        if body["type"] not in TYPES:
            raise SettingsError("Choose none, sole proprietor or S-corp.")
        writes["type"] = body["type"]
    if "home_office" in body:
        ho = _object(body["home_office"])
        if ho.get("method") not in HOME_OFFICE_METHODS:
            raise SettingsError("Choose no home office, the simplified method or actual expenses.")
        sq = "Enter square feet as a whole number from 0 to 100,000."
        value = HomeOffice(ho["method"], _whole(ho.get("office_sqft", 0), 0, MAX_SQFT, sq),
                           _whole(ho.get("home_sqft", 0), 0, MAX_SQFT, sq),
                           _whole(ho.get("home_costs_cents", 0), 0, MAX_HOME_COSTS,
                                  "Enter the yearly home costs from $0 to $10,000,000."))
        if value.method == "actual" and value.office_sqft > value.home_sqft:
            raise SettingsError("The office can't be bigger than the home.")
        writes[f"home_office:{year}"] = json.dumps(asdict(value))
    if "car_method" in body:
        if body["car_method"] not in CAR_METHODS:
            raise SettingsError("Choose standard mileage or actual costs.")
        writes[f"car_method:{year}"] = body["car_method"]
    if "miles" in body:
        m = body["miles"]
        msg = "Enter business miles as whole numbers, one for each rate period."
        if not isinstance(m, list) or len(m) != periods:
            raise SettingsError(msg)
        writes[f"miles:{year}"] = json.dumps([_whole(x, 0, MAX_MILES, msg) for x in m])
    if "expect" in body:
        if year != this_year:
            raise SettingsError("Expected profit is for this year only.")
        if body["expect"] is None:
            writes[f"expect:{year}"] = None
        else:
            e = _object(body["expect"])
            msg = "Enter the low and high as whole numbers of cents."
            low = _whole(e.get("low_cents"), -MAX_PROFIT, MAX_PROFIT, msg)
            high = _whole(e.get("high_cents"), -MAX_PROFIT, MAX_PROFIT, msg)
            if low > high:
                raise SettingsError("The low can't be more than the high.")
            writes[f"expect:{year}"] = json.dumps({"low_cents": low, "high_cents": high})
    if "s_corp" in body:
        s = _object(body["s_corp"])
        value = SCorp(_whole(s.get("salary_pct"), 1, 100, "Enter the salary as a percent of profit from 1 to 100."),
                      _whole(s.get("cost_cents"), 0, MAX_SCORP_COST, "Enter the yearly cost from $0 to $100,000."))
        writes["s_corp"] = json.dumps(asdict(value))
    if "owner" in body:
        if body["owner"] not in OWNERS:
            raise SettingsError("Choose who runs the business.")
        writes["owner"] = body["owner"]
    for name in YEARLY:
        if f"{name}:{year}" not in writes:
            continue
        have = _own_years(db, name)
        for later in range(year + 1, this_year + 1):
            shown = _yearly(db, name, later)
            if later not in have and shown is not None:
                _put(db, f"{name}:{later}", shown, user_id, at)
    for key, value in writes.items():
        _put(db, key, value, user_id, at)
    db.flush()
