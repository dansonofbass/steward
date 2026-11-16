"""The dated business tables (spec 3.2): src/steward/engine/data/rules/business_<year>.json. A year without a table
uses the latest earlier table, and `using_note` says so; a year before every table is an error."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

RULES_DIR = Path(__file__).resolve().parents[1] / "engine" / "data" / "rules"


class RulesTableError(RuntimeError):
    """No business table covers the year asked for."""


@dataclass(frozen=True)
class MileagePeriod:
    start: date
    end: date
    tenths_of_cent: int          # 725 is 72.5 cents a mile


@dataclass(frozen=True)
class BusinessRules:
    year: int
    asked_year: int
    home_office_rate_cents: int
    home_office_max_sqft: int
    meals_pct: int
    mileage: tuple[MileagePeriod, ...]
    source: str
    checked: str

    @property
    def using_note(self) -> str | None:
        return f"Using {self.year} rules" if self.year != self.asked_year else None


@cache
def _years() -> tuple[int, ...]:
    return tuple(sorted(int(p.stem.split("_")[1]) for p in RULES_DIR.glob("business_*.json")))


@cache
def _load(year: int) -> dict:
    return json.loads((RULES_DIR / f"business_{year}.json").read_text())


def business_rules(year: int) -> BusinessRules:
    have = [y for y in _years() if y <= year]
    if not have:
        raise RulesTableError(f"No business rules table covers {year}.")
    t = _load(have[-1])
    return BusinessRules(
        year=t["year"], asked_year=year,
        home_office_rate_cents=t["home_office"]["rate_cents_per_sqft"],
        home_office_max_sqft=t["home_office"]["max_sqft"],
        meals_pct=t["meals_pct"],
        mileage=tuple(MileagePeriod(date.fromisoformat(p["from"]), date.fromisoformat(p["to"]), p["tenths_of_cent"])
                      for p in t["mileage"]),
        source=t["source"], checked=t["checked"])

