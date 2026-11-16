"""The household's year for the tax engine (spec 7): one TaxFacts from Set up's facts, the business range and the
children, shared by Quarterly taxes, Solo 401(k) or SEP, and Roth or traditional (rulings 3, 14, 19). What Steward
doesn't hold (interest, dividends, gains, itemized deductions, the spouse's pay) is left out and said so."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy.orm import Session

from steward.business.report import ProfitRange, profit_range
from steward.business.settings import business_type, owner_index
from steward.db.models import active_children
from steward.engine.decisions import k401_limit_cents
from steward.engine.tax.facts import TaxFacts
from steward.services.plan_inputs import latest_facts

NEEDS = "Add both birth dates, your state and how you file taxes in Set up first."
FILING_ONLY = "Taxes work for married filing jointly or single."
LEFT_OUT = "Interest, dividends, gains and itemized deductions such as mortgage interest aren't counted."
SCORP = "The business is figured as a sole proprietor: S-corp payroll isn't calculated."
ADD_RANGE = "Add what you expect for the rest of the year in Business; until then only profit so far counts."
DEPENDENT_UNDER = 19
Point = Literal["so_far", "low", "mid", "high"]


class NotReady(Exception):
    """The household's tax facts aren't there yet; the message is in plain words."""


@dataclass(frozen=True)
class HouseholdTax:
    year: int
    facts: TaxFacts
    jr_age: int
    salary_cents: int
    w2_deferrals_cents: int        # the W-2 401(k) deferrals, pre-tax and Roth, within the year's limit
    business: str                  # none | sole_prop | s_corp
    range: ProfitRange | None
    profit_cents: int
    notes: tuple[str, ...]


def _int(facts: dict, key: str) -> int:
    return int(facts[key].value) if key in facts else 0


def profit_at(rng: ProfitRange, point: Point) -> int:
    return {"so_far": rng.ytd_cents, "low": rng.low_cents, "mid": rng.mid_cents, "high": rng.high_cents}[point]


def household_tax(db: Session, year: int, today: date, point: Point = "high") -> HouseholdTax:
    f = latest_facts(db)
    filing = f["filing_status"].value if "filing_status" in f else None
    need = ["jr.dob", "state"] + (["spouse.dob"] if filing == "mfj" else [])
    if filing is None or any(k not in f for k in need):
        raise NotReady(NEEDS)
    if filing not in ("mfj", "single"):
        raise NotReady(FILING_ONLY)
    ages = tuple(min(max(year - date.fromisoformat(f[k].value).year, 0), 120) for k in need if k.endswith(".dob"))
    salary = _int(f, "jr.salary_cents")
    limit = k401_limit_cents(ages[0], year)
    deferrals = min(salary * _int(f, "jr.k401_pct_bp") // 10_000, limit)
    pretax = deferrals * (10_000 - _int(f, "jr.k401_roth_share_bp")) // 10_000
    btype = business_type(db)
    rng = profit_range(db, year, today) if btype != "none" else None
    profit = profit_at(rng, point) if rng is not None else 0
    kids = tuple(sorted(year - c.birth_year for c in db.scalars(active_children())
                        if 0 <= year - c.birth_year < DEPENDENT_UNDER))
    others = (0,) * (len(ages) - 1)
    facts = TaxFacts(filing=filing, ages=ages, state=f["state"].value, wages_cents=salary - pretax,
                     payroll_wages_cents=salary, business_profit_cents=profit, business_owner=owner_index(db, len(ages)),
                     ss_wages_by_person_cents=(salary, *others), dependents=kids)
    notes = [LEFT_OUT]
    if btype == "s_corp":
        notes.append(SCORP)
    if rng is not None and not rng.entered and year == today.year:
        notes.append(ADD_RANGE)
    return HouseholdTax(year, facts, ages[0], salary, deferrals, btype, rng, profit, tuple(notes))
