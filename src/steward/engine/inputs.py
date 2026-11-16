"""The frozen input bundle the engine takes. M2-B builds it from the vault (spec section 2.5).

Money is integer cents; yearly amounts are yearly; rates are basis points. Everything is in
today's dollars.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Literal

Sex = Literal["male", "female"]
Filing = Literal["mfj", "single"]
CostLevel = Literal["two_year", "in_state_public", "out_of_state_public", "private"]
COST_LEVELS: tuple[CostLevel, ...] = ("two_year", "in_state_public", "out_of_state_public", "private")
FILINGS: tuple[Filing, ...] = ("mfj", "single")
SEXES: tuple[Sex, ...] = ("male", "female")


class InputError(ValueError):
    """The bundle cannot be simulated. The message is in plain words."""


@dataclass(frozen=True)
class Mix:
    stock: float
    bond: float
    cash: float
    fee_bp: int = 0

    def __post_init__(self):
        _check_mix(self)


def _check_mix(m: Mix) -> None:
    shares = (m.stock, m.bond, m.cash)
    if (not all(math.isfinite(x) for x in shares) or min(shares) < 0
            or abs(m.stock + m.bond + m.cash - 1.0) > 1e-6):
        raise InputError("An asset mix needs non-negative stock, bond and cash shares that add up to 1.")
    if not math.isfinite(m.fee_bp) or m.fee_bp < 0:
        raise InputError("Fund fees can't be negative.")


@dataclass(frozen=True)
class Bucket:
    balance_cents: int
    mix: Mix


@dataclass(frozen=True)
class Person:
    birth_year: int
    sex: Sex
    earnings: tuple[tuple[int, int], ...] = ()  # (year, earnings_cents); empty = no earnings record
    estimated: bool = False                     # the record is Steward's estimate from salary (profile spec P24)


@dataclass(frozen=True)
class Child:
    label: str
    birth_year: int
    cost_level: CostLevel
    plan529: Bucket
    monthly_contribution_cents: int
    share_pct: int = 100              # profile spec: the share of college the household plans to cover
    covers_living: bool = True        # False: tuition and fees only


@dataclass(frozen=True)
class OneOffCost:
    """A big cost paid once in its year, in today's dollars (phase 11c, decision D): a roof, a water heater, a car."""
    year: int
    cents: int


@dataclass(frozen=True)
class Household:
    plan_year: int
    jr: Person
    spouse: Person
    filing_status: Filing
    state: str
    salary_cents: int
    k401_pct_bp: int
    k401_roth_share_bp: int
    match_rate_bp: int
    match_cap_bp: int
    spending_basis_cents: int      # yearly, spec 2.5 "spending basis"
    spending_months: int           # months of history behind the basis (12 normally)
    surplus_cents: int             # yearly take-home surplus; may be negative
    mortgage_payment_cents: int    # yearly principal and interest
    mortgage_payoff_year: int | None
    health_premium_cents: int      # yearly household premium before Medicare
    cash: Bucket
    taxable: Bucket
    traditional: Bucket
    roth: Bucket
    hsa: Bucket
    children: tuple[Child, ...] = ()
    stale_notes: tuple[str, ...] = ()
    default_mix_symbols: tuple[str, ...] = ()
    business_owner: int = 0        # who runs the business: 0 = Person 1, 1 = Person 2; Person 1's wages count toward the SE wage base only when 0
    one_off_costs: tuple[OneOffCost, ...] = ()   # phase 11c: paid in their year as college shortfalls are


@dataclass(frozen=True)
class Levers:
    save_more_monthly_cents: int = 0
    spending_pct: int = 100
    consulting_cents: int = 0          # yearly; 0 = off
    consulting_until_age: int = 60     # Person 1's age at which consulting stops
    gift_cents: int = 0                # yearly; 0 = off
    gift_until_year: int = 0           # last calendar year the gift arrives
    spouse_earnings_cents: int = 0     # yearly; 0 = off
    spouse_start_year: int = 0         # first calendar year of the spouse's earnings
    spouse_stop_age: int = 65          # spouse's age at which the earnings stop
    jr_claim_age: int = 67
    spouse_claim_age: int = 67
    college_levels: tuple[CostLevel, ...] | None = None  # per child; None = each child's own level
    full_ss_benefits: bool = False     # True = no trust-fund cut


@dataclass(frozen=True)
class EngineInputs:
    household: Household
    levers: Levers = Levers()


def digest(inputs: EngineInputs) -> str:
    text = json.dumps(asdict(inputs), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _int(value) -> bool:
    """A whole number. True and False are not (bool is an int subclass in Python)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _cents(name: str, value: int, allow_negative: bool = False) -> None:
    if not _int(value) or (value < 0 and not allow_negative):
        raise InputError(f"The {name} must be a whole number of cents" + ("" if allow_negative else " and not negative") + ".")


def _bp(name: str, value: int) -> None:
    if not _int(value) or not 0 <= value <= 10_000:
        raise InputError(f"The {name} must be between 0 and 10,000 basis points.")


def _person(label: str, p: Person, plan_year: int) -> None:
    if p.sex not in SEXES:
        raise InputError(f"{label}'s sex must be 'male' or 'female' (it only sets the life table).")
    if not _int(p.birth_year) or p.birth_year >= plan_year:
        raise InputError(f"{label} must be born before the plan year.")
    years = [y for y, _ in p.earnings]
    if len(set(years)) != len(years) or any(not _int(y) or y < 1937 or y > plan_year for y in years):
        raise InputError(f"{label}'s earnings record must have one amount per year, 1937 or later, not in the future.")
    if any(not _int(c) or c < 0 for _, c in p.earnings):
        raise InputError(f"{label}'s earnings record has a negative or non-integer amount.")


def validate(inputs: EngineInputs) -> None:
    hh = inputs.household
    if not _int(hh.plan_year) or not 2000 <= hh.plan_year <= 2100:
        raise InputError("The plan year must be between 2000 and 2100.")
    _person("{person1}", hh.jr, hh.plan_year)          # filled with the household's labels where the text is shown
    _person("{person2}", hh.spouse, hh.plan_year)
    if min(hh.plan_year - hh.jr.birth_year, hh.plan_year - hh.spouse.birth_year) >= 95:
        raise InputError("The younger spouse is already 95 or older; there is nothing left to plan to.")
    if hh.filing_status not in FILINGS:
        raise InputError("The filing status must be 'mfj' or 'single'.")
    if not (isinstance(hh.state, str) and len(hh.state) == 2 and hh.state.isalpha() and hh.state.isupper()):
        raise InputError("The state must be a two-letter code like CA.")
    _cents("salary", hh.salary_cents)
    _bp("401(k) percentage", hh.k401_pct_bp)
    _bp("Roth 401(k) share", hh.k401_roth_share_bp)
    _bp("match rate", hh.match_rate_bp)
    _bp("match cap", hh.match_cap_bp)
    _cents("spending basis", hh.spending_basis_cents)
    if not _int(hh.spending_months) or not 1 <= hh.spending_months <= 12:
        raise InputError("The spending basis must rest on between 1 and 12 months of history.")
    _cents("take-home surplus", hh.surplus_cents, allow_negative=True)
    _cents("mortgage payment", hh.mortgage_payment_cents)
    if hh.mortgage_payoff_year is not None and not _int(hh.mortgage_payoff_year):
        raise InputError("The mortgage payoff year must be a year or left out.")
    _cents("health premium", hh.health_premium_cents)
    for name, b in (("cash", hh.cash), ("taxable", hh.taxable), ("traditional", hh.traditional), ("Roth", hh.roth), ("HSA", hh.hsa)):
        _cents(f"{name} balance", b.balance_cents)
        _check_mix(b.mix)
    for c in hh.children:
        if c.cost_level not in COST_LEVELS:
            raise InputError(f"{c.label}'s college cost level must be one of {', '.join(COST_LEVELS)}.")
        if not _int(c.share_pct) or not 0 <= c.share_pct <= 100:
            raise InputError(f"{c.label}'s college share must be a whole percent from 0 to 100.")
        if not isinstance(c.covers_living, bool):
            raise InputError(f"{c.label}'s living costs choice must be true or false.")
        if not _int(c.birth_year) or c.birth_year > hh.plan_year + 1:
            raise InputError(f"{c.label}'s birth year must be a year that has happened.")
        _cents(f"{c.label}'s 529 balance", c.plan529.balance_cents)
        _check_mix(c.plan529.mix)
        _cents(f"{c.label}'s monthly 529 contribution", c.monthly_contribution_cents)
    for c in hh.one_off_costs:
        if not _int(c.year) or not 2000 <= c.year <= 2200:
            raise InputError("A one-off cost's year must be between 2000 and 2200.")
        _cents("one-off cost", c.cents)
    lv = inputs.levers
    if lv.college_levels is not None:
        if len(lv.college_levels) != len(hh.children) or any(l not in COST_LEVELS for l in lv.college_levels):
            raise InputError("college_levels must name one valid level per child, or be left out.")
    for name, v in (("save_more_monthly_cents", lv.save_more_monthly_cents), ("consulting_cents", lv.consulting_cents),
                    ("gift_cents", lv.gift_cents), ("spouse_earnings_cents", lv.spouse_earnings_cents)):
        _cents(name.replace("_", " "), v)
    for name, v, hi in (("jr_claim_age", lv.jr_claim_age, 120), ("spouse_claim_age", lv.spouse_claim_age, 120),
                        ("consulting_until_age", lv.consulting_until_age, 120),
                        ("spouse_stop_age", lv.spouse_stop_age, 120), ("spending_pct", lv.spending_pct, 1000)):
        if not _int(v) or not 0 <= v <= hi:
            raise InputError(f"{name.replace('_', ' ')} must be a whole number from 0 to {hi}.")
    for name, v in (("gift_until_year", lv.gift_until_year), ("spouse_start_year", lv.spouse_start_year)):
        if not _int(v) or v < 0:
            raise InputError(f"{name.replace('_', ' ')} must be a year, or 0 for none.")
