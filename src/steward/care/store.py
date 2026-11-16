"""Care's saved rows (migration 0015) read into plain values: the setup, the scenarios in order and the quotes.
Writes live in steward.care.edit."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.care.costs import Quote
from steward.db.models import CareQuote, CareScenario, CareSetup

SCENARIO_FIELDS = ("level", "start_year", "hours_week", "adult_day_days", "room", "sell_home_year", "home_price_cents",
                   "home_basis_cents", "selling_cost_bp", "family_monthly_cents", "spending_change_monthly_cents")


@dataclass(frozen=True)
class Setup:
    person: str
    birth_year: int
    spouse_birth_year: int | None
    state: str
    care_inflation_bp: int
    spending_monthly_cents: int | None

    @property
    def care_inflation(self) -> float:
        return self.care_inflation_bp / 10_000


@dataclass(frozen=True)
class Scenario:
    id: int
    level: str
    start_year: int | None = None          # None: care starts now
    hours_week: int | None = None          # in-home help
    adult_day_days: int | None = None      # in-home help, optional
    room: str | None = None                # nursing home: "shared" or "private"
    sell_home_year: int | None = None
    home_price_cents: int | None = None    # None: the home's value in the inventory
    home_basis_cents: int | None = None    # None: no purchase price entered (ruling 10)
    selling_cost_bp: int = 600
    family_monthly_cents: int = 0
    spending_change_monthly_cents: int = 0


def read_setup(db: Session) -> Setup | None:
    row = db.get(CareSetup, 1)
    if row is None:
        return None
    return Setup(row.person, row.birth_year, row.spouse_birth_year, row.state, row.care_inflation_bp,
                 row.spending_monthly_cents)


def scenario_of(row: CareScenario) -> Scenario:
    return Scenario(id=row.id, **{f: getattr(row, f) for f in SCENARIO_FIELDS})


def read_scenarios(db: Session) -> list[Scenario]:
    return [scenario_of(r) for r in db.scalars(select(CareScenario).order_by(CareScenario.position, CareScenario.id))]


def read_quotes(db: Session) -> dict[str, Quote]:
    return {q.key: Quote(q.key, q.cents, q.quoted_on) for q in db.scalars(select(CareQuote))}
