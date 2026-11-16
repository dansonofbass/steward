import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward import deps
from steward.db.models import Fact
from steward.deps import BookContext, book_db, household_only, open_book, today
from steward.engine.next_dollar import HSA_PLAN_ANSWERS, MAX_CASH_MONTHS
from steward.services import home_value
from steward.services.undo import capturing

PLAN_FACT_KEYS = ("jr.salary_cents", "jr.k401_pct_bp", "jr.k401_roth_share_bp", "employer.match_rate_bp",
                  "employer.match_cap_bp", "mortgage.payment_cents", "health.premium_cents")
# What a paycheck put into the HSA or the employer 401(k) this year (final review ruling I3): one dated fact per person,
# counted only in its as_of year. Only Person 1 has W-2 pay in the household model today.
PAYROLL_FACT_KEYS = ("jr.payroll_hsa_cents", "jr.payroll_k401_cents")
MAX_PAYROLL_CENTS = 10_000_000                         # $100,000 a year
GIVING_OUTSIDE_MAX_CENTS = 10_000_000                  # $100,000 a month: giving outside these accounts (P13)
NEXT_DOLLAR_FACT_KEYS = ("next_dollar.cash_months", "next_dollar.debt_rate_bp", "health.hsa_plan", *PAYROLL_FACT_KEYS)
FACT_KEYS = ("jr.dob", "spouse.dob", "state", "filing_status", "home.value_cents",
             "mortgage.rate_bp", "mortgage.payoff_date", "home.owns", "jr.ss_estimate", "spouse.ss_estimate",
             "giving.outside_cents",
             *PLAN_FACT_KEYS, *NEXT_DOLLAR_FACT_KEYS)
_PERCENT_KEYS = tuple(k for k in PLAN_FACT_KEYS if k.endswith("_bp"))
_AMOUNT_KEYS = tuple(k for k in PLAN_FACT_KEYS if k.endswith("_cents"))
# Above these is a typo, as with MAX_MONTHLY_CENTS in api/children.py.
MAX_CENTS = {"jr.salary_cents": 1_000_000_000,        # $10,000,000 a year
             "mortgage.payment_cents": 10_000_000,    # $100,000 a month
             "health.premium_cents": 100_000_000}     # $1,000,000 a year
assert set(MAX_CENTS) == set(_AMOUNT_KEYS)

router = APIRouter(prefix="/facts", dependencies=[Depends(open_book), Depends(household_only)])


class FactIn(BaseModel):
    key: str
    value: str
    as_of: date | None = None
    note: str | None = None


FILING_STATUSES = ("single", "mfj", "mfs", "hoh")
STATE_CODES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK "
    "OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())
_INT = re.compile(r"-?[0-9]{1,15}")
_RATE = re.compile(r"[0-9]{1,5}(\.[0-9])?")   # ruling 7: 2.875% is 287.5 basis points


def _check_value(key: str, value: str) -> str | None:
    """Return a plain-words error for a bad value, or None if it is fine."""
    if key == "giving.outside_cents":
        ok = _INT.fullmatch(value) and 0 <= int(value) <= GIVING_OUTSIDE_MAX_CENTS
        return None if ok else f"Enter an amount from $0 to ${GIVING_OUTSIDE_MAX_CENTS // 100:,} a month."
    if key == "home.owns":
        return None if value in ("yes", "no") else "Choose yes or no."
    if key.endswith(".ss_estimate"):
        return None if value == "yes" else "Say yes to use Steward's estimate."
    if key == "next_dollar.cash_months":
        ok = _INT.fullmatch(value) and 1 <= int(value) <= MAX_CASH_MONTHS
        return None if ok else f"Enter a whole number of months from 1 to {MAX_CASH_MONTHS}."
    if key == "next_dollar.debt_rate_bp":
        ok = _INT.fullmatch(value) and 0 <= int(value) <= 10_000
        return None if ok else "Enter a percentage between 0 and 100."
    if key == "health.hsa_plan":
        return None if value in HSA_PLAN_ANSWERS else "Choose yes, no or not sure."
    if key in PAYROLL_FACT_KEYS:
        ok = _INT.fullmatch(value) and 0 <= int(value) <= MAX_PAYROLL_CENTS
        return None if ok else f"Enter an amount from $0 to ${MAX_PAYROLL_CENTS // 100:,}."
    if key == "mortgage.rate_bp":
        if not _RATE.fullmatch(value):
            return "Enter basis points with at most one decimal place."
        return None if float(value) <= 10_000 else "Enter a percentage between 0 and 100."
    if key.endswith("_cents") and not _INT.fullmatch(value):
        return "Enter a whole number of cents."
    if key.endswith("_bp") and not _INT.fullmatch(value):
        return "Enter a whole number of basis points."
    if key in _PERCENT_KEYS and not 0 <= int(value) <= 10_000:
        return "Enter a percentage between 0 and 100."
    if key in _AMOUNT_KEYS and int(value) < 0:
        return "Enter an amount that isn't negative."
    if key in MAX_CENTS and int(value) > MAX_CENTS[key]:
        return f"Enter an amount up to ${MAX_CENTS[key] // 100:,}."
    if key.endswith(".dob") or key.endswith("_date"):
        try:
            date.fromisoformat(value)
        except ValueError:
            return "Enter a date like 2026-10-12."
    if key == "state" and value not in STATE_CODES:
        return "Choose a state."
    if key == "filing_status" and value not in FILING_STATUSES:
        return "Choose single, mfj, mfs or hoh."
    return None


def _out(f: Fact) -> dict:
    return {"value": f.value, "as_of": f.as_of.isoformat(), "note": f.note}


@router.get("")
def latest(db: Session = Depends(book_db)):
    out: dict[str, dict] = {}
    for f in db.scalars(select(Fact).order_by(Fact.as_of.asc(), Fact.id.asc())):
        out[f.key] = _out(f)  # later rows overwrite earlier: latest wins
    return {"facts": out}


@router.get("/{key}/history")
def history(key: str, db: Session = Depends(book_db)):
    if key not in FACT_KEYS:
        raise HTTPException(404, detail={"error": "Unknown fact key."})
    rows = db.scalars(select(Fact).where(Fact.key == key).order_by(Fact.as_of.desc(), Fact.id.desc()))
    return {"history": [_out(f) for f in rows]}


@router.post("", status_code=201)
def add(body: FactIn, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    if body.key not in FACT_KEYS:
        raise HTTPException(422, detail={"error": "Unknown fact key."})
    value = body.value.strip().upper() if body.key == "state" else body.value
    problem = _check_value(body.key, value)
    if problem:
        raise HTTPException(422, detail={"error": problem})
    with capturing(db, ctx.user_id, "fact", deps.now()) as cap:
        f = Fact(key=body.key, value=value, as_of=body.as_of or today(), note=body.note)
        db.add(f)
        if body.key == home_value.VALUE_KEY:   # one home value: the Home account's balance becomes it (roadmap 11)
            home_value.value_saved(db, int(value), f.as_of, [o.key for o in ctx.book.owner_names])
    db.commit()
    return {"key": f.key, **_out(f), "undo": cap.token}
