"""Care's writes (spec 4: managers edit). Each checks its input, writes, and records the change for the parent book's
change record (family books spec 5; ruling 19). Callers commit. The first setup also makes the two default scenarios
(ruling 3); a book compares 1 to 5 scenarios (ruling 16)."""
from __future__ import annotations

from steward import clock
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.care import costs as C
from steward.care.scenarios import label
from steward.care.store import SCENARIO_FIELDS, scenario_of
from steward.care.vocab import COST_KEYS, LEVELS, MAX_SCENARIOS, ROOMS
from steward.db.models import CareQuote, CareScenario, CareSetup
from steward.engine.tax import rules
from steward.engine.tax.state import STATE_NAMES
from steward.inventory.changes import record
from steward.inventory.present import long_date, short_usd

PERSON_RULE = "Choose who Care is for."
BIRTH_RULE = "Enter the year born, from 1900 to {this}."
SPOUSE_RULE = "Enter the spouse's year born, from 1900 to {this}, or leave it blank."
STATE_RULE = "Choose a state."
GROWTH_RULE = "Enter how fast care costs rise, from 0% to 15% a year."
SPENDING_RULE = "Enter monthly spending in dollars and cents, or leave it blank."
LEVEL_RULE = "Choose a kind of care."
START_RULE = "Choose a start year from {this} to {last}, or now."
HOURS_RULE = "Enter hours a week, from 1 to 168."
DAYS_RULE = "Enter adult day days a week, from 0 to 5."
ROOM_RULE = "Choose a shared or a private room."
SALE_YEAR_RULE = "Choose the year the home is sold, from {this} to {last}."
PRICE_RULE = "Enter the expected price in dollars and cents."
NO_HOME = "Enter the expected price; there's no home in the inventory to start from."
BASIS_RULE = "Enter what was paid for the home plus improvements, or leave it blank."
SELLING_RULE = "Enter selling costs from 0% to 20%."
FAMILY_RULE = "Enter what family adds each month in dollars and cents."
CHANGE_RULE = "Enter the change in monthly spending in dollars and cents."
TOO_MANY = "Care compares up to 5 scenarios. Remove one first."
LAST_ONE = "Keep at least one scenario."
NOT_SET_UP = "Set up Care first."
NO_SUCH_SCENARIO = "No such scenario."
QUOTE_KEY_RULE = "Choose a care cost."
QUOTE_RULE = "Enter the quote in dollars and cents."
QUOTE_DATE_RULE = "Enter the date of the quote, like 2026-10-02, no later than today."
NO_QUOTE = "There's no quote for that cost."
MAX_CENTS = 10**11
MAX_MONTHLY = 10**9
AHEAD_YEARS = 40


class CareRefused(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return clock.now()


def _int(value: object, lo: int, hi: int, rule: str, *, required: bool = False) -> int | None:
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise CareRefused(rule)
    return value


def _summary(row: CareSetup, owners: dict[str, str]) -> str:
    out = f"{owners.get(row.person, row.person)}, born {row.birth_year}"
    if row.spouse_birth_year:
        out += f", spouse born {row.spouse_birth_year}"
    out += f", {STATE_NAMES.get(row.state, row.state)}, care costs rise {row.care_inflation_bp / 100:g}% a year"
    if row.spending_monthly_cents is not None:
        out += f", spending {C.dollars(row.spending_monthly_cents)} a month typed in"
    return out


def save_setup(db: Session, ctx, body: dict, today: date) -> bool:
    owners = {o.key: o.label for o in ctx.owners}
    this = today.year
    person = body.get("person")
    if not isinstance(person, str) or person not in owners or person == "joint":
        raise CareRefused(PERSON_RULE)
    birth = _int(body.get("birth_year"), 1900, this, BIRTH_RULE.format(this=this), required=True)
    spouse = _int(body.get("spouse_birth_year"), 1900, this, SPOUSE_RULE.format(this=this))
    state = body.get("state", "CA")
    if not isinstance(state, str) or state not in STATE_NAMES:
        raise CareRefused(STATE_RULE)
    growth = _int(body.get("care_inflation_bp", 400), 0, 1500, GROWTH_RULE, required=True)
    spending = _int(body.get("spending_monthly_cents"), 0, MAX_MONTHLY, SPENDING_RULE)
    row = db.get(CareSetup, 1)
    created = row is None
    before = None if created else {"summary": _summary(row, owners)}
    t = _now()
    if created:
        row = CareSetup(id=1)
        db.add(row)
    row.person, row.birth_year, row.spouse_birth_year, row.state = person, birth, spouse, state
    row.care_inflation_bp, row.spending_monthly_cents = growth, spending
    row.updated_at, row.updated_by = t, ctx.user_id
    if created:
        for pos, (level, start) in enumerate((("at_home", None), ("assisted_living", this + 1))):
            db.add(CareScenario(position=pos, level=level, start_year=start, created_at=t, created_by=ctx.user_id,
                                updated_at=t, updated_by=ctx.user_id))
    db.flush()
    after = {"summary": _summary(row, owners)}
    if before != after:
        record(db, ctx, "care.setup", before=before, after=after)
    return created


def clean_scenario(body: dict, current: dict, this_year: int, home_value: int | None) -> dict:
    """The scenario's fields after `body`, checked. A saved year already gone means now (Review Focus 2)."""
    out = {f: current.get(f) for f in SCENARIO_FIELDS}
    if "start_year" not in body and out.get("start_year") is not None and out["start_year"] < this_year:
        out["start_year"] = None
    if "sell_home_year" not in body and out.get("sell_home_year") is not None and out["sell_home_year"] < this_year:
        out["sell_home_year"] = this_year
    for f in SCENARIO_FIELDS:
        if f in body:
            out[f] = body[f]
    last = this_year + AHEAD_YEARS
    level = out.get("level")
    if not isinstance(level, str) or level not in LEVELS:
        raise CareRefused(LEVEL_RULE)
    out["start_year"] = None if level == "at_home" else _int(out.get("start_year"), this_year, last,
                                                              START_RULE.format(this=this_year, last=last))
    if level == "in_home_help":
        out["hours_week"] = _int(out.get("hours_week"), 1, 168, HOURS_RULE, required=True)
        out["adult_day_days"] = _int(out.get("adult_day_days"), 0, 5, DAYS_RULE)
    else:
        out["hours_week"] = out["adult_day_days"] = None
    if level == "nursing_home":
        room = out.get("room") or "shared"
        if not isinstance(room, str) or room not in ROOMS:
            raise CareRefused(ROOM_RULE)
        out["room"] = room
    else:
        out["room"] = None
    out["sell_home_year"] = _int(out.get("sell_home_year"), this_year, last,
                                 SALE_YEAR_RULE.format(this=this_year, last=last))
    if out["sell_home_year"] is None:
        out["home_price_cents"] = out["home_basis_cents"] = None
        out["selling_cost_bp"] = 600
    else:
        out["home_price_cents"] = _int(out.get("home_price_cents"), 1, MAX_CENTS, PRICE_RULE)
        if out["home_price_cents"] is None and not home_value:
            raise CareRefused(NO_HOME)
        out["home_basis_cents"] = _int(out.get("home_basis_cents"), 0, MAX_CENTS, BASIS_RULE)
        bp = out.get("selling_cost_bp")
        out["selling_cost_bp"] = _int(600 if bp is None else bp, 0, 2000, SELLING_RULE, required=True)
    fam, change = out.get("family_monthly_cents"), out.get("spending_change_monthly_cents")
    out["family_monthly_cents"] = _int(0 if fam is None else fam, 0, MAX_MONTHLY, FAMILY_RULE, required=True)
    out["spending_change_monthly_cents"] = _int(0 if change is None else change, -MAX_MONTHLY, MAX_MONTHLY,
                                                CHANGE_RULE, required=True)
    return out


def add_scenario(db: Session, ctx, body: dict, today: date, home_value: int | None) -> CareScenario:
    if db.get(CareSetup, 1) is None:
        raise CareRefused(NOT_SET_UP, 409)
    if db.scalar(select(func.count()).select_from(CareScenario)) >= MAX_SCENARIOS:
        raise CareRefused(TOO_MANY)
    fields = clean_scenario(body, {}, today.year, home_value)
    t = _now()
    row = CareScenario(position=(db.scalar(select(func.max(CareScenario.position))) or 0) + 1, created_at=t,
                       created_by=ctx.user_id, updated_at=t, updated_by=ctx.user_id, **fields)
    db.add(row)
    db.flush()
    record(db, ctx, "care.scenario_add", target_id=row.id, after={"label": label(scenario_of(row), today.year)})
    return row


def edit_scenario(db: Session, ctx, row: CareScenario, body: dict, today: date, home_value: int | None) -> None:
    current = {f: getattr(row, f) for f in SCENARIO_FIELDS}
    fields = clean_scenario(body, current, today.year, home_value)
    if fields == current:
        return
    before = label(scenario_of(row), today.year)
    for f, v in fields.items():
        setattr(row, f, v)
    row.updated_at, row.updated_by = _now(), ctx.user_id
    db.flush()
    record(db, ctx, "care.scenario_edit", target_id=row.id, before={"label": before},
           after={"label": label(scenario_of(row), today.year)})


def remove_scenario(db: Session, ctx, row: CareScenario, today: date) -> None:
    if db.scalar(select(func.count()).select_from(CareScenario)) <= 1:
        raise CareRefused(LAST_ONE)
    gone = label(scenario_of(row), today.year)
    db.delete(row)
    db.flush()
    record(db, ctx, "care.scenario_remove", target_id=row.id, before={"label": gone})


def set_quote(db: Session, ctx, key: str, body: dict, today: date) -> None:
    if key not in COST_KEYS:
        raise CareRefused(QUOTE_KEY_RULE)
    cents = _int(body.get("cents"), 1, MAX_MONTHLY, QUOTE_RULE, required=True)
    raw = body.get("quoted_on")
    try:
        on = date.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        on = None
    if on is None or on > today or on.year < 2000:
        raise CareRefused(QUOTE_DATE_RULE)
    row = db.get(CareQuote, key)
    if row is None:
        row = CareQuote(key=key)
        db.add(row)
    row.cents, row.quoted_on, row.updated_at, row.updated_by = cents, on, _now(), ctx.user_id
    db.flush()
    per = rules.table("care_costs", today.year)["figures"][key]["per"]
    record(db, ctx, "care.quote", after={"label": C.LABELS[key],
                                         "text": f"{short_usd(cents)} {C.PER_WORDS[per]}, quoted {long_date(on)}"})


def remove_quote(db: Session, ctx, key: str) -> None:
    if key not in COST_KEYS:
        raise CareRefused(QUOTE_KEY_RULE)
    row = db.get(CareQuote, key)
    if row is None:
        raise CareRefused(NO_QUOTE, 404)
    db.delete(row)
    db.flush()
    record(db, ctx, "care.quote_remove", before={"label": C.LABELS[key]})
