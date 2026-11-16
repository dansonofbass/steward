"""The Care screen's answer (spec 4). compute() gathers everything once; care_out() turns it into the JSON the screen
reads. The chat tool (steward.advisor.tools.care) reads compute() too, so the screen and Claude see the same figures."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from steward.care import costs as C
from steward.care import medi_cal as M
from steward.care.book import CareBook, load_book
from steward.care.monthly import Monthly, month_by_month
from steward.care.scenarios import ScenarioResult, assumptions_for, projection_years, run_all
from steward.care.store import SCENARIO_FIELDS, Setup, read_quotes, read_scenarios, read_setup
from steward.care.vocab import COST_KEYS, MAX_SCENARIOS
from steward.engine.project import Assumptions
from steward.engine.tax import rules

NO_SPENDING = "Spending: no transactions yet, so none is counted. Type a monthly figure in Care setup."
UNDATED_ONE = "1 income or premium has no usual day or renewal date, so it isn't listed."
UNDATED_N = "{n} incomes or premiums have no usual day or renewal date, so they aren't listed."
PREMIUM_STOPS = "Long-term care premiums stop once the policy starts paying, as most policies waive them."
NOT_CALIFORNIA = "Typical care costs are California figures. Enter quotes for the costs where {name} lives."


@dataclass(frozen=True)
class CareView:
    setup: Setup | None
    book: CareBook | None
    figures: dict[str, C.Figure]
    results: tuple[ScenarioResult, ...]
    monthly: Monthly
    limit: M.Limit | None
    look_back_months: int


def compute(db: Session, owners: dict[str, str], today: date) -> CareView:
    setup = read_setup(db)
    monthly = month_by_month(db, today)
    if setup is None:
        return CareView(None, None, {}, (), monthly, None, 0)
    book = load_book(db, setup, owners, today)
    figs = C.figures(read_quotes(db), today.year, setup.care_inflation)
    results = tuple(run_all(book, read_scenarios(db), figs, assumptions_for(setup.care_inflation)))
    people = 2 if setup.spouse_birth_year is not None else 1
    return CareView(setup, book, figs, results, monthly, M.asset_limit(today.year, people),
                    rules.table("medi_cal", today.year)["look_back_months"])


def spending_line(book: CareBook) -> str:
    monthly = (book.spending_yearly_cents + 6) // 12
    if book.spending_typed:
        return f"Spending: {C.dollars(monthly)} a month, typed in."
    if book.spending_months == 0:
        return NO_SPENDING
    months = "month" if book.spending_months == 1 else f"{book.spending_months} months"
    return f"Spending: {C.dollars(monthly)} a month, from the last {months} of transactions, taxes and transfers left out."


def how(view: CareView) -> list[str]:
    a, s, b = Assumptions(), view.setup, view.book
    last_age = b.age + projection_years(b.age) - 1          # 100, or sooner at the 40-year cap (final review M4)
    lines = [spending_line(b),
             f"Amounts are in today's dollars: prices rise {a.inflation * 100:g}% a year and savings earn "
             f"{a.real_return * 100:g}% a year more than that.",
             f"Care costs rise {s.care_inflation_bp / 100:g}% a year.",
             "Social Security keeps pace with prices; pensions and annuities stay the same in dollars.",
             f"Each year counts in full, this year included, and the projection runs to age {last_age}."]
    if b.policies:
        lines.append(PREMIUM_STOPS)
    if view.results:
        lines.append(view.results[0].tax_line)
    if s.state != "CA":
        lines.append(NOT_CALIFORNIA.format(name=b.person_label))
    return lines


def scenario_out(r: ScenarioResult) -> dict:
    s = r.scenario
    return {"id": s.id, **{f: getattr(s, f) for f in SCENARIO_FIELDS}, "label": r.label, "levers": list(r.levers),
            "care_monthly_cents": r.care_monthly_cents, "cost_lines": list(r.cost_lines), "headline": r.headline,
            "lasts_until": r.lasts_until, "ltc_line": r.ltc_line, "ltc_runs_out": r.ltc_runs_out,
            "medi_cal_line": r.medi_cal_line, "medi_cal_when": r.medi_cal_when,
            "medi_cal_first_year": r.medi_cal_first_year,
            "years": [{"year": y.year, "age": y.age, "balance_cents": y.balance_cents, "care_cents": y.care_cents,
                       "ltc_cents": y.ltc_cents, "tax_cents": y.tax_cents, "short_cents": y.short_cents,
                       "home_sale_cents": y.home_sale_cents, "medi_cal": y.medi_cal.status,
                       "medi_cal_over_cents": y.medi_cal.over_cents} for y in r.years]}


def cost_out(f: C.Figure) -> dict:
    return {"key": f.key, "label": f.label, "per": f.per, "cents": f.cents, "text": C.figure_text(f), "line": f.line,
            "quote": {"cents": f.base_cents, "quoted_on": f.quoted_on.isoformat()} if f.quoted_on else None}


def monthly_out(m: Monthly) -> dict:
    undated = None if m.undated == 0 else UNDATED_ONE if m.undated == 1 else UNDATED_N.format(n=m.undated)
    return {"months": m.months,
            "expected": [{"on": e.on.isoformat(), "label": e.label, "cents": e.cents, "source": e.source}
                         for e in m.expected],
            "expected_in_cents": m.expected_in_cents, "expected_out_cents": m.expected_out_cents,
            "cash_cents": m.cash_cents, "floors_cents": m.floors_cents, "above_floor_cents": m.above_floor_cents,
            "short_line": m.short_line, "short_cents": m.short_cents, "undated_line": undated}


def care_out(view: CareView, owners: dict[str, str], today: date) -> dict:
    out = {"this_year": today.year, "set_up": view.setup is not None, "max_scenarios": MAX_SCENARIOS,
           "people": [{"key": k, "label": v} for k, v in owners.items() if k != "joint"],
           "setup": None, "age": None, "home_value_cents": None, "spending": None, "scenarios": [], "costs": [],
           "medi_cal": None, "how": [], "notes": [], "monthly": monthly_out(view.monthly)}
    if view.setup is None:
        return out
    s, b = view.setup, view.book
    out.update(
        setup={"person": s.person, "person_label": b.person_label, "birth_year": s.birth_year,
               "spouse_birth_year": s.spouse_birth_year, "state": s.state, "care_inflation_bp": s.care_inflation_bp,
               "spending_monthly_cents": s.spending_monthly_cents},
        age=b.age, home_value_cents=b.home_value_cents,
        spending={"monthly_cents": (b.spending_yearly_cents + 6) // 12, "months": b.spending_months,
                  "typed": b.spending_typed, "line": spending_line(b)},
        scenarios=[scenario_out(r) for r in view.results], costs=[cost_out(view.figures[k]) for k in COST_KEYS],
        medi_cal={"rule_line": M.rule_line(view.limit), "url": view.limit.url, "disclaimer": M.DISCLAIMER,
                  "topics": M.topics(view.look_back_months, view.limit.rules_year)},
        how=how(view), notes=list(b.notes))
    return out
