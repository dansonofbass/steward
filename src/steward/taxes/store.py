"""What the household enters for Taxes, in tax_state (ruling 21). Keys: return:<year> (JSON ReturnFigures),
withholding:<year> (JSON Withholding), payment:<transaction id> ("other": not an estimate; no row: it counts),
email:<user id> ("on"; no row: off, ruling 11), sent:<due date> (JSON: the reminder's progress). Every write checks
its values first and writes nothing when one is refused."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import TaxState

MAX_CENTS = 10_000_000_000      # $100,000,000
RETURN_FIELDS = ("federal_tax_cents", "federal_agi_cents", "state_tax_cents", "state_agi_cents")
WITHHOLDING_FIELDS = frozenset({"federal_ytd_cents", "state_ytd_cents", "as_of"})
NOT_UNDERSTOOD = "That request wasn't understood."
AMOUNT = "Enter amounts from $0 to $100,000,000, or leave them blank."
PAY_DATE = "Enter the pay date from a {year} pay stub, not in the future."


class StoreError(ValueError):
    """A value Taxes can't take; the message is in plain words."""


@dataclass(frozen=True)
class ReturnFigures:
    federal_tax_cents: int | None = None     # Form 1040 line 24 less refundable credits
    federal_agi_cents: int | None = None
    state_tax_cents: int | None = None       # Form 540 lines 48, 61 and 62 together
    state_agi_cents: int | None = None       # Form 540 line 17


@dataclass(frozen=True)
class Withholding:
    federal_ytd_cents: int
    state_ytd_cents: int
    as_of: date                              # the pay stub's date


def _get(db: Session, key: str) -> str | None:
    row = db.get(TaxState, key)
    return row.value if row is not None else None


def _put(db: Session, key: str, value: str | None, user_id: int | None, at: datetime) -> None:
    row = db.get(TaxState, key)
    if value is None:
        if row is not None:
            db.delete(row)
        return
    if row is None:
        db.add(TaxState(key=key, value=value, updated_at=at, updated_by=user_id))
    else:
        row.value, row.updated_at, row.updated_by = value, at, user_id


def _cents(v, message: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= MAX_CENTS:
        raise StoreError(message)
    return v


def read_return(db: Session, year: int) -> ReturnFigures | None:
    raw = _get(db, f"return:{year}")
    return ReturnFigures(**json.loads(raw)) if raw else None


def write_return(db: Session, year: int, body: dict, user_id: int, at: datetime) -> ReturnFigures:
    if not isinstance(body, dict) or set(body) - set(RETURN_FIELDS):
        raise StoreError(NOT_UNDERSTOOD)
    figs = ReturnFigures(**{k: None if body.get(k) is None else _cents(body[k], AMOUNT) for k in RETURN_FIELDS})
    blank = all(v is None for v in asdict(figs).values())
    _put(db, f"return:{year}", None if blank else json.dumps(asdict(figs)), user_id, at)
    db.flush()
    return figs


def read_withholding(db: Session, year: int) -> Withholding | None:
    raw = _get(db, f"withholding:{year}")
    if not raw:
        return None
    d = json.loads(raw)
    return Withholding(d["federal_ytd_cents"], d["state_ytd_cents"], date.fromisoformat(d["as_of"]))


def write_withholding(db: Session, year: int, body: dict, *, today: date, user_id: int, at: datetime) -> Withholding:
    if not isinstance(body, dict) or set(body) != WITHHOLDING_FIELDS:
        raise StoreError(NOT_UNDERSTOOD)
    try:
        as_of = date.fromisoformat(str(body["as_of"]))
    except ValueError:
        raise StoreError(PAY_DATE.format(year=year)) from None
    # Wages and withholding are reported by pay date, so a stub dated after December 31 carries the next year's pay
    # only (final review I1).
    if not date(year, 1, 1) <= as_of <= min(today, date(year, 12, 31)):
        raise StoreError(PAY_DATE.format(year=year))
    w = Withholding(_cents(body["federal_ytd_cents"], AMOUNT), _cents(body["state_ytd_cents"], AMOUNT), as_of)
    _put(db, f"withholding:{year}", json.dumps({"federal_ytd_cents": w.federal_ytd_cents,
                                                 "state_ytd_cents": w.state_ytd_cents, "as_of": as_of.isoformat()}),
         user_id, at)
    db.flush()
    return w


def _ids(db: Session, prefix: str, value: str) -> list[int]:
    out = []
    for key, v in db.execute(select(TaxState.key, TaxState.value).where(TaxState.key.like(f"{prefix}:%"))):
        suffix = key[len(prefix) + 1:]
        if v == value and suffix.isascii() and suffix.isdigit():
            out.append(int(suffix))
    return sorted(out)


def not_estimates(db: Session) -> set[int]:
    return set(_ids(db, "payment", "other"))


def estimates(db: Session) -> set[int]:
    """Payments someone counted that would start uncounted (an EFTPS payment from a business account)."""
    return set(_ids(db, "payment", "estimate"))


def mark_payment(db: Session, txn_id: int, counts: bool, user_id: int, at: datetime) -> None:
    _put(db, f"payment:{txn_id}", "estimate" if counts else "other", user_id, at)
    db.flush()


def email_on(db: Session, user_id: int) -> bool:
    return _get(db, f"email:{user_id}") == "on"


def set_email(db: Session, user_id: int, on: bool, at: datetime) -> None:
    _put(db, f"email:{user_id}", "on" if on else None, user_id, at)
    db.flush()


def email_users(db: Session) -> list[int]:
    return _ids(db, "email", "on")


def sent_mark(db: Session, due: date) -> dict | None:
    raw = _get(db, f"sent:{due.isoformat()}")
    return json.loads(raw) if raw else None


def put_sent_mark(db: Session, due: date, mark: dict, at: datetime) -> None:
    _put(db, f"sent:{due.isoformat()}", json.dumps(mark), None, at)
    db.flush()
