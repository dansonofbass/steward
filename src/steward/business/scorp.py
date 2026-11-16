"""The S-corp comparison (spec 5.4; ruling 14). At the profit range's low, middle and high (or year to date when no
range is entered): the household's total tax as a sole proprietor against the total tax with a reasonable salary
(salary_pct of profit, a setting) plus the yearly cost of payroll and the extra return (cost_cents, $1,500 by
default). The S-corp side adds both halves of payroll tax on the salary and the state's S-corp costs (California's
franchise tax, employer UI and ETT, and SDI), all from steward.engine.tax. Steward compares; it never runs payroll."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from steward.business.report import profit_range
from steward.business.settings import owner_index, read_settings
from steward.engine.tax import payroll_tax, scorp_state_costs, state_name
from steward.engine.tax.annual import annual_tax
from steward.engine.tax.facts import TaxFacts
from steward.services.plan_inputs import latest_facts

NEEDS = "Add both birth dates, your state and how you file taxes in Set up first."
FILING_ONLY = "The comparison works for married filing jointly or single."
STATE_COSTS = "Includes {state}'s S-corp franchise tax, employer unemployment and training taxes, and SDI on the salary."
ADD_RANGE = "Add what you expect for the rest of the year to compare the full year."


class NotReady(Exception):
    """The household's tax facts aren't there yet; the message is in plain words."""


@dataclass(frozen=True)
class ScorpPoint:
    label: str
    profit_cents: int
    salary_cents: int
    sole_tax_cents: int
    scorp_tax_cents: int
    cost_cents: int
    saves_cents: int
    payroll_cents: int = 0         # both halves of payroll tax on the salary (in scorp_tax_cents)
    franchise_cents: int = 0       # the state's tax on the S-corp (in scorp_tax_cents)
    sdi_cents: int = 0             # state payroll tax withheld from the salary (in scorp_tax_cents)
    unemployment_cents: int = 0    # the employer's state payroll taxes on the salary (in scorp_tax_cents)


@dataclass(frozen=True)
class Comparison:
    year: int
    points: tuple[ScorpPoint, ...]
    worth_it: bool
    line: str
    salary_pct: int
    cost_cents: int
    rules_note: str = ""
    state_note: str = ""


@dataclass(frozen=True)
class _Household:
    filing: str
    ages: tuple[int, ...]
    state: str
    wages: int                     # Person 1's W-2 wages (the only salary the model holds)
    owner: int = 0                 # who runs the business, an index into ages (final review ruling I2)

    def owner_wages(self) -> int:
        return self.wages if self.owner == 0 else 0


def _household(db: Session, year: int) -> _Household:
    f = latest_facts(db)
    filing = f["filing_status"].value if "filing_status" in f else None
    need = ["jr.dob", "state"] + (["spouse.dob"] if filing == "mfj" else [])
    if filing is None or any(k not in f for k in need):
        raise NotReady(NEEDS)
    if filing not in ("mfj", "single"):
        raise NotReady(FILING_ONLY)
    ages = tuple(year - date.fromisoformat(f[k].value).year for k in need if k.endswith(".dob"))
    wages = int(f["jr.salary_cents"].value) if "jr.salary_cents" in f else 0
    return _Household(filing, ages, f["state"].value, wages, owner_index(db, len(ages)))


def _facts(h: _Household, profit: int, salary: int | None, deductions: int = 0, state_addback: int = 0) -> TaxFacts:
    """Part 1's TaxFacts (money in cents). The W-2 wages are Person 1's; the owner is whoever runs the business, so
    Schedule SE (and the S-corp salary) count only the owner's own wages against the wage base. An S-corp's salary is W-2 wages, the rest of
    the profit is K-1 income with no self-employment tax, and the salary is the wages the business paid (the business
    income deduction's wage limit). `deductions` are the S-corp's other business costs (the employer half of payroll
    tax, the yearly running cost and the state's franchise tax), which lower the K-1 income."""
    by_person = [h.wages] + [0] * (len(h.ages) - 1)
    if salary is None:
        return TaxFacts(filing=h.filing, ages=h.ages, state=h.state, wages_cents=h.wages, business_profit_cents=profit,
                        ss_wages_by_person_cents=tuple(by_person), business_owner=h.owner)
    by_person[h.owner] += salary
    return TaxFacts(filing=h.filing, ages=h.ages, state=h.state, wages_cents=h.wages + salary,
                    scorp_profit_cents=profit - salary - deductions, business_w2_wages_cents=salary,
                    state_addback_cents=state_addback,
                    ss_wages_by_person_cents=tuple(by_person), business_owner=h.owner)


def _total(result) -> int:
    return int(result.total_tax_cents)


def _about(cents: int) -> str:
    return f"${round(cents / 10_000) * 100:,}"


def compare(db: Session, year: int, today: date, tax=annual_tax) -> Comparison:
    h = _household(db, year)
    s = read_settings(db, year).s_corp
    rng = profit_range(db, year, today)
    if rng.entered:
        targets = [("low", rng.low_cents), ("middle", rng.mid_cents), ("high", rng.high_cents)]
    else:
        targets = [("so far", rng.ytd_cents)]
    points = []
    rules_year = 0
    state_year = 0
    state_note = ""
    for label, profit in targets:
        if profit <= 0:
            points.append(ScorpPoint(label, profit, 0, 0, 0, s.cost_cents, 0))
            continue
        salary = profit * s.salary_pct // 100
        sole_result = tax(_facts(h, profit, None), year)
        sole = _total(sole_result)
        rules_year = max(rules_year, sole_result.rules_year)
        payroll = payroll_tax(salary, year, other_ss_wages_cents=h.owner_wages())
        costs = scorp_state_costs(h.state, salary, profit - salary - payroll.employer_cents - s.cost_cents, year)
        state_note = STATE_COSTS.format(state=state_name(h.state)) if costs.calculated else costs.explain[0]
        if costs.calculated and costs.rules_year and costs.rules_year < year:
            state_year = max(state_year, costs.rules_year)
        scorp_result = tax(_facts(h, profit, salary, payroll.employer_cents + s.cost_cents + costs.franchise_cents
                                              + costs.unemployment_cents, state_addback=costs.franchise_cents), year)
        scorp = _total(scorp_result) + payroll.total_cents + costs.total_cents
        rules_year = max(rules_year, scorp_result.rules_year)
        for r in (sole_result, scorp_result):
            st = getattr(r, "state", None)
            if st is not None and 0 < st.rules_year < year:
                state_year = max(state_year, st.rules_year)
        points.append(ScorpPoint(label, profit, salary, sole, scorp, s.cost_cents, sole - scorp - s.cost_cents,
                                 payroll.total_cents, costs.franchise_cents, costs.sdi_cents, costs.unemployment_cents))
    middle = points[1] if len(points) == 3 else points[0]
    worth_it = middle.saves_cents > 0
    at = "at your profit" if rng.entered else "at your profit so far"
    if worth_it:
        line = f"An S-corp would save about {_about(middle.saves_cents)} a year {at}."
    else:
        line = f"Not yet worth it {at}." + ("" if rng.entered else f" {ADD_RANGE}")
    if 0 < rules_year < year:
        note = f"Using {rules_year} rules"
    elif state_year:
        note = f"{year} federal and {state_year} {state_name(h.state)} rules"
    else:
        note = f"{year} tax rules"
    return Comparison(year, tuple(points), worth_it, line, s.salary_pct, s.cost_cents, note, state_note)


def comparison_out(c: Comparison) -> dict:
    return {"available": True, "year": c.year, "line": c.line, "worth_it": c.worth_it, "salary_pct": c.salary_pct,
            "cost_cents": c.cost_cents, "rules_note": c.rules_note, "state_note": c.state_note,
            "points": [{"label": p.label, "profit_cents": p.profit_cents, "salary_cents": p.salary_cents,
                        "sole_tax_cents": p.sole_tax_cents, "scorp_tax_cents": p.scorp_tax_cents,
                        "cost_cents": p.cost_cents, "saves_cents": p.saves_cents, "payroll_cents": p.payroll_cents,
                        "franchise_cents": p.franchise_cents, "sdi_cents": p.sdi_cents,
                        "unemployment_cents": p.unemployment_cents} for p in c.points]}
