"""Margaret Ellis's care (parent care plan Task 9). Fictional throughout. Run after seed_parent on the same book:
Care set up for Margaret (born 1944, California), four scenarios side by side and one assisted living quote. Years
are relative to `today`."""
from __future__ import annotations

from steward import clock
from datetime import date, timedelta

from sqlalchemy.orm import Session

from steward.db.models import CareQuote, CareScenario, CareSetup


def seed_care(db: Session, today: date) -> None:
    now = clock.now()
    y = today.year
    db.add(CareSetup(id=1, person="margaret", birth_year=1944, spouse_birth_year=None, state="CA",
                     care_inflation_bp=400, spending_monthly_cents=None, updated_at=now))
    scenarios = ({"level": "at_home"},
                 {"level": "in_home_help", "hours_week": 20, "start_year": y},
                 {"level": "assisted_living", "start_year": y + 1},
                 {"level": "nursing_home", "room": "shared", "start_year": y + 3, "sell_home_year": y + 3,
                  "home_basis_cents": 9_500_000})
    for pos, fields in enumerate(scenarios):
        db.add(CareScenario(position=pos, created_at=now, updated_at=now, **fields))
    db.add(CareQuote(key="assisted_living_monthly", cents=645_000, quoted_on=today - timedelta(days=16), updated_at=now))
    db.commit()
