"""Quarterly estimated tax (spec 7.1), pure. When payments are due, the two methods, and each installment.

Each agency's dates come from its rule table (federal: Form 1040-ES; the state's module: California's Form 540-ES) as
month-day pairs, the January date in the following year. A date on a Saturday, Sunday or legal holiday moves to the
next business day (both forms say so). The holidays that can land on these dates are Martin Luther King Jr. Day (the
third Monday in January) and, for the IRS only, Emancipation Day in Washington, DC (April 16; observed on Friday the
15th when it falls on a Saturday, Monday the 17th on a Sunday). California doesn't observe Emancipation Day; whether
the FTB follows the IRS on it is unconfirmed and first matters in April 2028 (plan, Values that could not be
confirmed).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from steward.engine.tax import rules
from steward.engine.tax.facts import Installment
from steward.engine.tax.state import module_for

Agency = Literal["federal", "state"]
STATE_TOPICS = {"CA": "california"}


def _mlk_day(year: int) -> date:
    jan1 = date(year, 1, 1)
    first_monday = jan1 + timedelta(days=(0 - jan1.weekday()) % 7)
    return first_monday + timedelta(days=14)


def _emancipation_day(year: int) -> date:
    d = date(year, 4, 16)
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def next_business_day(d: date, agency: Agency) -> date:
    while True:
        holidays = {_mlk_day(d.year)}
        if agency == "federal":
            holidays.add(_emancipation_day(d.year))
        if d.weekday() < 5 and d not in holidays:
            return d
        d += timedelta(days=1)


def _installment_date(year: int, month_day: str) -> date:
    """A payment date for the tax year: January's falls in the next calendar year."""
    month, day = (int(x) for x in month_day.split("-"))
    return date(year + 1 if month == 1 else year, month, day)


def _next_year(year: int, month_day: str) -> date:
    month, day = (int(x) for x in month_day.split("-"))
    return date(year + 1, month, day)


def schedule(year: int, agency: Agency, state: str) -> tuple[Installment, ...]:
    """Each due date for the tax year, moved to a business day, and its share of the year's payment. () for a state
    with no estimate schedule (no wage tax, or not calculated yet)."""
    if agency == "federal":
        e = rules.table("federal", year)["estimates"]
        return tuple(Installment(next_business_day(_installment_date(year, d), "federal"), s)
                     for d, s in zip(e["due"], e["shares"]))
    mod = module_for(state)
    if mod is None:
        return ()
    return tuple(Installment(next_business_day(i.due, "state"), i.share) for i in mod.estimates_schedule(year))


def last_federal_due(year: int) -> date:
    """The tax year's January payment date, moved to a business day."""
    return next_business_day(_installment_date(year, rules.table("federal", year)["estimates"]["due"][-1]), "federal")


def tax_year_for(today: date) -> int:
    """The year whose payments are still ahead (ruling 2): last year until its January date has passed."""
    return today.year - 1 if today <= last_federal_due(today.year - 1) else today.year


def return_due(year: int) -> date:
    """When the year's federal return is due (26 U.S.C. 6072(a)), moved to a business day."""
    return next_business_day(_next_year(year, rules.table("federal", year)["returns"]["due"]), "federal")


def extended_return_due(year: int) -> date:
    return next_business_day(_next_year(year, rules.table("federal", year)["returns"]["extended_due"]), "federal")


# The worksheets (Form 1040-ES lines 12-15; Form 540-ES lines 19-22): the required annual payment is the smaller of
# 90% of this year's tax and 100% of last year's (110% when last year's AGI was over $150,000; California also needs
# this year's tax at a California AGI of $1,000,000 or more). Withholding comes off it and each date pays its share of
# what is left. Nothing is needed when this year's tax less withholding is under the minimum ($1,000 federal, $500
# California). What is still due at a date is everything scheduled through it less the payments made by then.

Method = Literal["current_year", "prior_year", "none_needed"]


@dataclass(frozen=True)
class PriorYear:
    tax_cents: int
    agi_cents: int


@dataclass(frozen=True)
class Due:
    due: date
    share: float
    installment_cents: int     # this date's part of the balance
    by_then_cents: int         # everything scheduled through this date
    paid_cents: int            # payments made on or before it
    still_due_cents: int       # by_then less paid, never below zero


@dataclass(frozen=True)
class AgencyPlan:
    agency: Agency
    rules_year: int
    minimum_cents: int
    current_tax_cents: int
    current_required_cents: int        # 90% of this year's tax
    prior_required_cents: int | None   # 100% or 110% of last year's; None when not entered or not allowed
    prior_share: float | None
    prior_not_allowed: bool            # California at a California AGI of $1,000,000 or more
    withholding_cents: int
    method: Method
    required_cents: int                # the one recommended
    balance_cents: int                 # required less withholding, never below zero
    dues: tuple[Due, ...]
    paid_cents: int
    skip_fourth_if_filed_by: date


def _table(agency: Agency, state: str, year: int):
    if agency == "federal":
        return rules.table("federal", year)
    topic = STATE_TOPICS.get(state)
    return rules.table(topic, year) if topic else None


def agency_plan(agency: Agency, *, year: int, state: str, current_tax_cents: int, current_agi_cents: int,
                prior: PriorYear | None, withholding_cents: int,
                payments: Sequence[tuple[date, int]]) -> AgencyPlan | None:
    sched = schedule(year, agency, state)
    t = _table(agency, state, year)
    if not sched or t is None:
        return None
    e = t["estimates"]
    tax = max(current_tax_cents, 0)
    withholding = max(withholding_cents, 0)
    minimum = e["minimum_owed"] * 100
    current_required = round(tax * e["current_year_share"])
    only_current = e.get("current_year_only_agi")
    not_allowed = only_current is not None and current_agi_cents >= only_current * 100
    prior_required = share = None
    if prior is not None and not not_allowed:
        share = e["high_income_prior_year_share"] if prior.agi_cents > e["high_income_agi"] * 100 else e["prior_year_share"]
        prior_required = round(max(prior.tax_cents, 0) * share)
    if tax - withholding < minimum:
        method, required = "none_needed", 0
    elif prior_required is not None and prior_required < current_required:
        method, required = "prior_year", prior_required
    else:
        method, required = "current_year", current_required
    balance = 0 if method == "none_needed" else max(required - withholding, 0)
    dues: list[Due] = []
    cumulative, before = 0.0, 0
    for i, inst in enumerate(sched):
        cumulative += inst.share
        by_then = balance if i == len(sched) - 1 else min(round(balance * cumulative), balance)
        paid = sum(c for d, c in payments if d <= inst.due)
        dues.append(Due(inst.due, inst.share, by_then - before, by_then, paid, max(by_then - paid, 0)))
        before = by_then
    return AgencyPlan(agency=agency, rules_year=t.year, minimum_cents=minimum, current_tax_cents=tax,
                      current_required_cents=current_required, prior_required_cents=prior_required, prior_share=share,
                      prior_not_allowed=not_allowed, withholding_cents=withholding, method=method,
                      required_cents=required, balance_cents=balance, dues=tuple(dues),
                      paid_cents=sum(c for _, c in payments),
                      skip_fourth_if_filed_by=_next_year(year, e["skip_fourth_if_filed_by"]))
