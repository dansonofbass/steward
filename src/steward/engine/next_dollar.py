"""Where the next dollar goes (cash-flow and tax spec section 6), household books only.

Six steps in order, each with what is in already this year, the room left, and one plain sentence why:
1. cash for N months of spending; 2. the employer 401(k) match; 3. an HSA when the health plan qualifies; 4. debt above
the rate setting (7%); 5. the business plan (a Solo 401(k)) or a Roth IRA, whichever saves more this year
(steward.engine.decisions, refined by part 5); 6. taxable investing or extra mortgage payments, by the mortgage rate
against the expected return after tax. A step that doesn't apply (no employer match, a health plan that doesn't
qualify) is left out. With business income the cash target defaults to six months and the business plan's amount waits
for October, when the year's profit is clearer. Steward suggests; it never moves money.

Pure: no database. steward.services.next_dollar builds the inputs from the vault."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal

from steward.engine.decisions import business_plan_room, hsa_limit, retirement_choice, roth_ira_limit
from steward.engine.inputs import InputError
from steward.engine.tax import annual_tax
from steward.engine.tax.facts import TaxFacts, TaxResult

CASH_MONTHS_BUSINESS = 6
CASH_MONTHS_OTHER = 3
MAX_CASH_MONTHS = 24
DEFAULT_DEBT_RATE_BP = 700
LATE_YEAR_MONTH = 10            # October: from here on the business plan's amount is suggested
GAIN_STEP_CENTS = 10_000        # the next $100 of long-term gains, for the tax on investing
HSA_PLAN_ANSWERS = ("yes", "no", "unsure")

StepKey = Literal["cash", "match", "hsa", "debt", "retirement", "invest"]
Status = Literal["done", "to_do", "later", "ask", "no_room", "cant_tell"]
Choice = Literal["business_plan", "roth_ira", "mortgage", "invest"]


@dataclass(frozen=True)
class Debt:
    account_id: int
    name: str
    owed_cents: int                  # what is owed, positive
    rate_bp: float | None            # yearly interest in basis points; None: not entered
    interest_charged: bool           # interest charged on the account in the last 90 days
    is_mortgage: bool = False


@dataclass(frozen=True)
class NextDollarInputs:
    year: int
    month: int                       # today's month, 1-12
    owners: tuple[str, ...]          # the adults' names, in the order of ages
    ages: tuple[int, ...]            # each adult's age on December 31
    spending_basis_cents: int        # yearly
    cash_cents: int                  # checking and savings
    cash_months: int
    has_business: bool
    business_profit_low_cents: int   # Schedule C profit at the low end of this year's range; 0 without a business
    salary_cents: int
    k401_pct_bp: int
    match_rate_bp: int
    match_cap_bp: int
    k401_in_cents: int | None        # transfers into the employer 401(k) this year; None: no history
    hsa_plan: str | None             # one of HSA_PLAN_ANSWERS; None: not asked yet
    hsa_family: bool
    has_hsa_account: bool
    hsa_in_cents: int | None
    ira_in_cents: tuple[int, ...]    # each adult's IRA transfers this year, in the order of ages
    business_plan_in_cents: int | None   # transfers into a 401(k) owned by Business this year
    debts: tuple[Debt, ...]
    debt_rate_bp: int
    taxable_in_cents: int | None
    now: TaxFacts                    # this year
    later: TaxFacts                  # a retirement year, for retirement_choice
    real_return: float               # expected yearly growth above inflation on the taxable account's mix
    inflation: float
    business_owner: int = 0          # index into owners of the adult who runs the business
    business_owner_w2_deferral_cents: int = 0   # that adult's own W-2 401(k) deferrals this year (not their spouse's)
    hsa_payroll_cents: int | None = None         # put into the HSA through payroll this year, as entered; None: blank
    k401_payroll_cents: int | None = None        # put into the employer 401(k) through payroll this year; None: blank
    later_rate: float | None = None  # the projection's rate in retirement (tax decisions plan Task 8); None: the later facts'


@dataclass(frozen=True)
class Step:
    key: StepKey
    title: str
    status: Status
    why: str
    in_cents: int | None = None      # in already this year (tagged transfers); None: not measured
    room_cents: int | None = None    # left to put in: this year's room, the cash still short, or what is owed
    rules_year: int | None = None    # the rule table year behind the numbers
    choice: Choice | None = None
    needs_rate: tuple[tuple[int, str], ...] = ()   # (account id, name) of accounts whose rate would help
    takes_payroll: bool = False      # the step counts money put in through payroll, entered by the household
    payroll_cents: int | None = None # that amount; None: not entered (with W-2 wages, the HSA's room isn't shown)


def _d(cents: float) -> str:
    return f"${round(cents / 100):,}"


def _pct(bp: float) -> str:
    return f"{bp / 100:.3f}".rstrip("0").rstrip(".") + "%"


def _rate(r: float) -> str:
    return f"{round(r * 100)}%"


def _amounts(owners: tuple[str, ...], rooms: list[int]) -> str:
    if len(owners) == 1:
        return _d(rooms[0])
    given = [(n, r) for n, r in zip(owners, rooms) if r > 0]
    if len(given) == len(owners) and len({r for _, r in given}) == 1:
        return f"{_d(given[0][1])} for each of you"
    return " and ".join(f"{_d(r)} for {n}" for n, r in given)


def _validate(i: NextDollarInputs) -> None:
    if not i.ages or not (len(i.owners) == len(i.ages) == len(i.ira_in_cents) == len(i.now.ages)):
        raise InputError("Give one name, one age and one IRA total for each adult.")
    if not 0 <= i.business_owner < len(i.ages):
        raise InputError("The business owner must be one of the adults.")
    if not 1 <= i.cash_months <= MAX_CASH_MONTHS:
        raise InputError(f"The cash target must be from 1 to {MAX_CASH_MONTHS} months.")
    if not 0 <= i.debt_rate_bp <= 10_000:
        raise InputError("The debt rate must be between 0% and 100%.")
    if not 1 <= i.month <= 12:
        raise InputError("The month must be from 1 to 12.")
    if i.hsa_plan is not None and i.hsa_plan not in HSA_PLAN_ANSWERS:
        raise InputError("The HSA answer must be yes, no or unsure.")


def _cash(i: NextDollarInputs) -> Step:
    title = f"Cash for {i.cash_months} months of spending"
    if i.spending_basis_cents <= 0:
        return Step("cash", title, "cant_tell", "There is no spending history yet to set the target.",
                    in_cents=i.cash_cents)
    monthly = i.spending_basis_cents / 12
    short = max(0, math.ceil(monthly * i.cash_months) - i.cash_cents)
    held = math.floor(i.cash_cents / monthly * 10) / 10
    because = ", because business income is uncertain" if i.has_business else ""
    return Step("cash", title, "done" if short == 0 else "to_do",
                f"Cash accounts hold {held:.1f} months of spending; the target is {i.cash_months}{because}.",
                in_cents=i.cash_cents, room_cents=short)


def _match(i: NextDollarInputs) -> Step | None:
    if i.salary_cents <= 0 or i.match_rate_bp <= 0 or i.match_cap_bp <= 0:
        return None
    title = "Employer 401(k) match"
    pct, cap = f"{i.k401_pct_bp / 100:g}%", f"{i.match_cap_bp / 100:g}%"
    put_in = _with_payroll(i.k401_in_cents, i.k401_payroll_cents)
    paid = dict(in_cents=put_in, takes_payroll=True, payroll_cents=i.k401_payroll_cents)
    if i.k401_pct_bp >= i.match_cap_bp:
        return Step("match", title, "done", f"Contributing {pct} of pay meets the {cap} match.", room_cents=0, **paid)
    extra = i.salary_cents * (i.match_cap_bp - i.k401_pct_bp) // 10_000
    gained = extra * i.match_rate_bp // 10_000
    return Step("match", title, "to_do",
                f"Contributing {pct} of pay; raising it to {cap} adds {_d(gained)} a year from the employer.",
                room_cents=extra, **paid)


def _with_payroll(tagged: int | None, payroll: int | None) -> int | None:
    """In so far: the tagged transfers plus what the household entered as put in through payroll (ruling I3)."""
    if tagged is None and payroll is None:
        return None
    return (tagged or 0) + (payroll or 0)


def _hsa(i: NextDollarInputs) -> Step | None:
    if i.hsa_plan == "no":
        return None
    if i.hsa_plan is None:
        return Step("hsa", "HSA", "ask", "Does your health plan qualify for an HSA?")
    if i.hsa_plan == "unsure":
        return Step("hsa", "HSA", "ask", "The plan's summary of benefits says whether it is HSA-qualified.")
    limit, year = hsa_limit(i.hsa_family, i.ages, i.year)
    kind = "family" if i.hsa_family else "self-only"
    w2 = i.salary_cents > 0
    paid = dict(takes_payroll=w2, payroll_cents=i.hsa_payroll_cents if w2 else None)
    # With W-2 wages and no payroll amount entered, money the paycheck put in is unknown, so the room isn't shown.
    unknown = w2 and i.hsa_payroll_cents is None
    if not i.has_hsa_account and not (w2 and i.hsa_payroll_cents):
        return Step("hsa", "HSA", "to_do", f"Open an HSA; the {year} {kind} limit is {_d(limit)}.",
                    room_cents=None if unknown else limit, rules_year=year, **paid)
    put_in = (i.hsa_in_cents or 0) + ((i.hsa_payroll_cents or 0) if w2 else 0)
    left = max(0, limit - put_in)
    if left == 0:
        return Step("hsa", "HSA", "done", f"The {year} {kind} limit of {_d(limit)} is in.",
                    in_cents=put_in, room_cents=0, rules_year=year, **paid)
    room = None if unknown else left
    return Step("hsa", "HSA", "to_do", f"{_d(put_in)} in so far; the {year} {kind} limit is {_d(limit)}.",
                in_cents=put_in, room_cents=room, rules_year=year, **paid)


def _high_debts(i: NextDollarInputs) -> list[Debt]:
    """Debts over the rate setting. A card with no rate entered but interest charged lately counts (cards that charge
    interest almost always charge more than 7%) and asks for its rate; one with no interest is paid in full."""
    return [d for d in i.debts if d.owed_cents > 0 and (
        (d.rate_bp is not None and d.rate_bp > i.debt_rate_bp)
        or (d.rate_bp is None and d.interest_charged and not d.is_mortgage))]


def _debt(i: NextDollarInputs) -> Step:
    limit = _pct(i.debt_rate_bp)
    title = f"Debt above {limit} interest"
    high = sorted(_high_debts(i), key=lambda d: (d.rate_bp is None, -(d.rate_bp or 0), d.name))
    if not high:
        return Step("debt", title, "done", f"No debt above {limit} interest.", room_cents=0)
    names = ", ".join(f"{d.name} ({_pct(d.rate_bp)})" if d.rate_bp is not None else f"{d.name} (rate not entered)"
                      for d in high)
    owed = sum(d.owed_cents for d in high)
    why = f"{names}: {_d(owed)} owed." if len(high) == 1 else f"Highest rate first: {names}. {_d(owed)} owed in all."
    return Step("debt", title, "to_do", why, room_cents=owed,
                needs_rate=tuple((d.account_id, d.name) for d in high if d.rate_bp is None))


def _retirement(i: NextDollarInputs, now: TaxResult) -> Step:
    """The business plan or a Roth IRA, whichever saves more this year; when that one is full, the other one's room
    comes next, before taxable investing (final review ruling I1)."""
    choice = retirement_choice(i.now, i.later, i.year, rate_later=i.later_rate)
    # Earned income at the same low end of the profit range as the plan's room (final review minor b).
    earned = max(0, i.salary_cents) + (max(0, i.business_profit_low_cents) if i.has_business else 0)
    limits: list[int] = []
    year = i.year
    for age in i.ages:
        lim, year = roth_ira_limit(now.agi_cents, i.now.filing, age, i.year)
        limits.append(lim)
    rooms = [max(0, lim - put) for lim, put in zip(limits, i.ira_in_cents)]
    ira_in = sum(i.ira_in_cents)
    roth_room = min(sum(rooms), max(0, earned - ira_in))
    roth_open = earned > 0 and sum(limits) > 0
    has_plan = i.has_business and i.business_profit_low_cents > 0
    rates = f"{_rate(choice.now_rate)} now against about {_rate(choice.later_rate)} later ({choice.rules_year} rules)"
    plan_left = plan_year = 0
    if has_plan:
        se = annual_tax(replace(i.now, business_profit_cents=i.business_profit_low_cents), i.year,
                        marginal=False).federal.se_tax_cents
        total, plan_year = business_plan_room(i.business_profit_low_cents, se,
                                              max(0, i.business_owner_w2_deferral_cents), i.ages[i.business_owner],
                                              i.year)
        plan_left = max(0, total - (i.business_plan_in_cents or 0))

    def plan(lead: str, meanwhile_ok: bool = True) -> Step:
        if i.month < LATE_YEAR_MONTH and plan_left > 0:
            meanwhile = (f" Meanwhile a Roth IRA has {_d(roth_room)} of room."
                         if meanwhile_ok and roth_open and roth_room > 0 else "")
            return Step("retirement", "Solo 401(k)", "later",
                        f"{lead} Check back in October, once the year's profit is clearer.{meanwhile}",
                        in_cents=i.business_plan_in_cents, room_cents=None, rules_year=plan_year,
                        choice="business_plan")
        tail = (f"The room at the low end of your profit range is in ({plan_year} limits)." if plan_left == 0
                else f"Room at the low end of your profit range: {_d(plan_left)} ({plan_year} limits).")
        return Step("retirement", "Solo 401(k)", "done" if plan_left == 0 else "to_do", f"{lead} {tail}",
                    in_cents=i.business_plan_in_cents, room_cents=plan_left, rules_year=plan_year,
                    choice="business_plan")

    roth = lambda status, why, room: Step("retirement", "Roth IRA", status, why, in_cents=ira_in,  # noqa: E731
                                          room_cents=room, rules_year=year, choice="roth_ira")

    def roth_left(lead: str) -> Step:
        if roth_room < sum(rooms):
            return roth("to_do", f"{lead}Room left: {_d(roth_room)}, up to this year's earned income ({year} limits).",
                        roth_room)
        return roth("to_do", f"{lead}Room left: {_amounts(i.owners, rooms)} ({year} limits).", roth_room)

    if has_plan and (choice.lean == "pretax" or not roth_open):
        if plan_left == 0 and roth_open and roth_room > 0:
            return roth_left("The Solo 401(k) room at the low end of your profit range is in, so a Roth IRA is next. ")
        lead = (f"A Solo 401(k) saves more this year: {rates}." if choice.lean == "pretax"
                else f"Your income is over the {year} Roth IRA limit, so a Solo 401(k) is next.")
        return plan(lead)

    if earned <= 0:
        return roth("no_room", "A Roth IRA needs earned income this year.", 0)
    if sum(limits) == 0:
        return roth("no_room", f"Your income is over the {year} Roth IRA limit.", 0)
    if roth_room == 0:
        if has_plan and plan_left > 0:
            return plan("The Roth IRA limit is in, so a Solo 401(k) is next.", meanwhile_ok=False)
        if has_plan:
            return roth("done", f"The {year} Roth IRA limit is in, and so is the Solo 401(k) room at the low end of "
                                "your profit range.", 0)
        return roth("done", f"The {year} limit is in.", 0)
    return roth_left(f"A Roth IRA saves more this year: {rates}. " if has_plan else "")


def _invest(i: NextDollarInputs, now: TaxResult) -> Step:
    bumped = annual_tax(replace(i.now, long_term_gains_cents=i.now.long_term_gains_cents + GAIN_STEP_CENTS), i.year,
                        marginal=False)
    tax = max(0.0, (bumped.total_tax_cents - now.total_tax_cents) / GAIN_STEP_CENTS)
    after = ((1 + i.real_return) * (1 + i.inflation) - 1) * (1 - tax)
    expected = f"about {after * 100:.1f}% a year after tax ({now.rules_year} rules)"
    high = {d.account_id for d in _high_debts(i)}
    mortgage = next((d for d in i.debts if d.is_mortgage and d.owed_cents > 0), None)

    def invest(why: str, needs: tuple[tuple[int, str], ...] = ()) -> Step:
        return Step("invest", "Taxable investing", "to_do", why, in_cents=i.taxable_in_cents,
                    rules_year=now.rules_year, choice="invest", needs_rate=needs)

    if mortgage is None:
        return invest(f"No mortgage to pay down. Investing is expected to earn {expected}.")
    if mortgage.account_id in high:
        return invest(f"Investing is expected to earn {expected}. The mortgage is paid down first, above.")
    if mortgage.rate_bp is None:
        return invest(f"Investing is expected to earn {expected}. Enter the mortgage rate to compare it with paying "
                      "the mortgage down.", ((mortgage.account_id, mortgage.name),))
    if mortgage.rate_bp / 10_000 > after:
        return Step("invest", "Extra mortgage payments", "to_do",
                    f"The mortgage charges {_pct(mortgage.rate_bp)}; investing is expected to earn {expected}.",
                    room_cents=mortgage.owed_cents, rules_year=now.rules_year, choice="mortgage")
    return invest(f"Investing is expected to earn {expected}, more than the mortgage's {_pct(mortgage.rate_bp)}.")


def next_dollar(i: NextDollarInputs) -> tuple[Step, ...]:
    """The steps in the spec's order, leaving out those that don't apply."""
    _validate(i)
    now = annual_tax(i.now, i.year, marginal=False)
    steps = (_cash(i), _match(i), _hsa(i), _debt(i), _retirement(i, now), _invest(i, now))
    return tuple(s for s in steps if s is not None)
