"""Care scenarios side by side (spec 4.1). Each is a care level that starts now or in a chosen year, with levers (sell
the home, family adds money each month, spending changes), run through the engine's project() year by year in today's
dollars, with long-term care insurance from the inventory paying once care starts and the waiting period ends, and the
Medi-Cal check each year. Care costs count as medical expenses (ruling 8); today's spending continues unless the
spending change lowers it (ruling 9); a blank purchase price counts the whole price over the exclusion as gain (ruling
10). The projection runs to age 100, at most 40 years, each year in full (ruling 13)."""
from __future__ import annotations

from dataclasses import dataclass

from steward.care import costs as C
from steward.care import medi_cal as M
from steward.care.book import CareBook, PolicyTerms
from steward.care.store import Scenario
from steward.engine.project import (
    Assumptions, Expense, HomeSale, Income, LtcPolicy, ProjectionInputs, ltc_runs_out, money_lasts_until, project,
)
from steward.engine.tax import rules
from steward.engine.tax.facts import TaxResult
from steward.engine.tax.state import not_calculated_line, state_name

LAST_AGE = 100
MAX_YEARS = 40
LEVEL_LABELS = {"at_home": "At home as today", "in_home_help": "In-home help", "assisted_living": "Assisted living",
                "memory_care": "Memory care", "nursing_home": "Nursing home"}


@dataclass(frozen=True)
class YearOut:
    year: int
    age: int
    balance_cents: int
    income_cents: int
    care_cents: int
    ltc_cents: int
    tax_cents: int
    short_cents: int
    home_sale_cents: int
    medi_cal: M.MediCalYear


@dataclass(frozen=True)
class ScenarioResult:
    scenario: Scenario
    label: str
    levers: tuple[str, ...]
    care_monthly_cents: int            # today's dollars
    cost_lines: tuple[str, ...]        # each figure behind the care cost, with its source or quote
    care_start_year: int               # this year for at home
    quote: bool                        # a figure behind the care cost is the family's quote
    lasts_until: int | None            # the last fully paid year; before this year when it runs short now
    lasts_until_age: int | None
    last_age: int                      # the age in the last projected year
    headline: str
    ltc_pays_from: int | None
    ltc_runs_out: int | None
    ltc_line: str | None
    medi_cal_shown: M.MediCalYear      # the year care starts
    medi_cal_line: str
    medi_cal_first_year: int | None
    medi_cal_when: str
    tax_line: str
    years: tuple[YearOut, ...]


def projection_years(age: int) -> int:
    return max(1, min(MAX_YEARS, LAST_AGE - age + 1))


def care_start(s: Scenario, this_year: int) -> int:
    """Care starts now, or in its year; a year already gone means now (Review Focus 2)."""
    return this_year if s.start_year is None else max(s.start_year, this_year)


def label(s: Scenario, this_year: int) -> str:
    if s.level == "at_home":
        return LEVEL_LABELS["at_home"]
    parts = [LEVEL_LABELS[s.level]]
    if s.level == "in_home_help":
        hours = s.hours_week or 0
        parts.append(f"{hours} {'hour' if hours == 1 else 'hours'} a week")
        if s.adult_day_days:
            parts.append(f"adult day {s.adult_day_days} {'day' if s.adult_day_days == 1 else 'days'} a week")
    if s.level == "nursing_home":
        parts.append(f"{s.room or 'shared'} room")
    start = care_start(s, this_year)
    when = "starting now" if start == this_year else f"from {start}"
    return f"{', '.join(parts)}, {when}" if len(parts) > 1 else f"{parts[0]} {when}"


def sale_year(s: Scenario, this_year: int) -> int | None:
    """The year the home sells: None, or the chosen year, or now when that year is already gone."""
    return None if s.sell_home_year is None else max(s.sell_home_year, this_year)


def _filing(book: CareBook) -> str:
    return "mfj" if book.spouse_birth_year is not None else "single"


def _sale_price(book: CareBook, s: Scenario) -> int:
    return s.home_price_cents if s.home_price_cents is not None else (book.home_value_cents or 0)


def levers(book: CareBook, s: Scenario) -> tuple[str, ...]:
    out = []
    year = sale_year(s, book.this_year)
    if year is not None:
        line = (f"Home sold in {year} for {C.dollars(_sale_price(book, s))}, less {s.selling_cost_bp / 100:g}% "
                f"selling costs")
        if s.home_basis_cents is None:
            fed = rules.table("federal", year)
            exclusion = C.dollars(fed["home_sale_exclusion"][_filing(book)] * 100)
            line += (f"; no purchase price entered, so everything over the {exclusion} exclusion counts as gain "
                     f"({fed.year} rules)")
        out.append(line)
    if s.family_monthly_cents:
        start = care_start(s, book.this_year)
        when = "now" if start == book.this_year else str(start)
        out.append(f"Family adds {C.dollars(s.family_monthly_cents)} a month from {when}")
    if s.spending_change_monthly_cents > 0:
        out.append(f"Spending {C.dollars(s.spending_change_monthly_cents)} a month more")
    elif s.spending_change_monthly_cents < 0:
        out.append(f"Spending {C.dollars(-s.spending_change_monthly_cents)} a month less")
    return tuple(out)


def cost_keys(s: Scenario) -> tuple[str, ...]:
    if s.level == "at_home":
        return ()
    if s.level == "in_home_help":
        return ("in_home_hourly", "adult_day_daily") if s.adult_day_days else ("in_home_hourly",)
    if s.level == "nursing_home":
        return (f"nursing_home_{s.room or 'shared'}_monthly",)
    return (f"{s.level}_monthly",)


def _policy(p: PolicyTerms, start: int) -> LtcPolicy:
    return LtcPolicy(care_start_year=start, benefit_daily_cents=p.benefit_daily_cents,
                     benefit_monthly_cents=p.benefit_monthly_cents, waiting_days=p.waiting_days,
                     total_benefit_cents=p.total_benefit_cents, benefit_years=p.benefit_years,
                     benefit_growth=p.benefit_growth, premium_yearly_cents=p.premium_yearly_cents)


def inputs_for(book: CareBook, s: Scenario, care_monthly_cents: int) -> ProjectionInputs:
    this = book.this_year
    start = care_start(s, this)
    spending = max(book.spending_yearly_cents + 12 * s.spending_change_monthly_cents, 0)
    expenses = [Expense(label="Spending", amount_cents=spending, start_year=this, kind="spending")]
    if care_monthly_cents > 0:
        expenses.append(Expense(label=LEVEL_LABELS[s.level], amount_cents=12 * care_monthly_cents, start_year=start,
                                growth="care", kind="care", medical=True))
    incomes = list(book.incomes)
    if s.family_monthly_cents > 0:
        incomes.append(Income(label="Family", amount_cents=12 * s.family_monthly_cents, start_year=start,
                              kind="nontaxable"))         # from when care starts (final review M6)
    sale = None
    if s.sell_home_year is not None:
        sale = HomeSale(year=sale_year(s, this), price_cents=_sale_price(book, s),
                        basis_cents=s.home_basis_cents or 0, selling_cost_rate=s.selling_cost_bp / 10_000)
    mfj = book.spouse_birth_year is not None
    return ProjectionInputs(
        start_year=this, filing=_filing(book), state=book.state,
        birth_years=(book.birth_year, book.spouse_birth_year) if mfj else (book.birth_year,),
        cash_cents=book.cash_cents, taxable_cents=book.taxable_cents, traditional_cents=book.traditional_cents,
        roth_cents=book.roth_cents, incomes=tuple(incomes), expenses=tuple(expenses),
        ltc_policies=tuple(_policy(p, start) for p in book.policies), home_sale=sale)


def assumptions_for(care_inflation: float) -> Assumptions:
    return Assumptions(care_inflation=care_inflation)


def tax_line(tax: TaxResult) -> str:
    fed = f"Tax uses {tax.rules_year} federal rules"
    st = tax.state
    if not st.calculated:
        return f"{fed}. {not_calculated_line(st.state)}"
    if st.rules_year is not None:
        return f"{fed} and {st.rules_year} {state_name(st.state)} rules."
    return f"{fed}. {st.explain[0]}" if st.explain else f"{fed}."


def run(book: CareBook, s: Scenario, figs: dict[str, C.Figure], a: Assumptions, years: int | None = None) -> ScenarioResult:
    this = book.this_year
    monthly = C.monthly_cents(s.level, figs, hours_week=s.hours_week, adult_day_days=s.adult_day_days, room=s.room)
    rows = project(inputs_for(book, s, monthly), a, years or projection_years(book.age))
    people = 2 if book.spouse_birth_year is not None else 1
    checks = [M.check_year(r, book.birth_year, people) for r in rows]
    start = care_start(s, this)
    until = money_lasts_until(rows)
    last_age = rows[-1].ages[0]
    if until is None:
        headline = f"Lasts past age {last_age}"
    elif until < this:
        headline = f"Money runs short in {this} (age {this - book.birth_year})"
    else:
        headline = f"Money lasts until {until} (age {until - book.birth_year})"
    paid = [r.year for r in rows if r.ltc_benefit_cents > 0]
    runs_out = ltc_runs_out(rows)
    ltc_line = None
    if paid:
        ltc_line = (f"Long-term care insurance pays from {paid[0]} and runs out in {runs_out}." if runs_out
                    else f"Long-term care insurance pays from {paid[0]} and lasts past {rows[-1].year}.")
    shown = next((m for m in checks if m.year == start), checks[-1])
    first = M.first_eligible(checks)
    keys = cost_keys(s)
    return ScenarioResult(
        scenario=s, label=label(s, this), levers=levers(book, s), care_monthly_cents=monthly,
        cost_lines=tuple(f"{figs[k].label}: {C.figure_text(figs[k])}. {figs[k].line}" for k in keys),
        care_start_year=start, quote=any(figs[k].quoted_on is not None for k in keys), lasts_until=until,
        lasts_until_age=None if until is None else until - book.birth_year, last_age=last_age, headline=headline,
        ltc_pays_from=paid[0] if paid else None, ltc_runs_out=runs_out, ltc_line=ltc_line, medi_cal_shown=shown,
        medi_cal_line=f"Medi-Cal in {shown.year}: {M.status_line(shown)} ({shown.limit.rules_year} rules).",
        medi_cal_first_year=first,
        medi_cal_when=(f"Meets the Medi-Cal limit in {first} (age {first - book.birth_year})." if first
                       else f"Doesn't meet the Medi-Cal limit by age {last_age}."),
        tax_line=tax_line(rows[0].tax),
        years=tuple(YearOut(r.year, r.ages[0], r.balance_cents, r.income_cents, r.care_cents, r.ltc_benefit_cents,
                            r.tax_cents, r.shortfall_cents, r.home_sale_cents, m) for r, m in zip(rows, checks)))


def run_all(book: CareBook, scenarios: list[Scenario], figs: dict[str, C.Figure], a: Assumptions) -> list[ScenarioResult]:
    return [run(book, s, figs, a) for s in scenarios]
