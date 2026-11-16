"""Social Security: the official benefit formula on an earnings record, claiming adjustments,
spousal and survivor rules, and the household's monthly benefit in a given year of a history.

Today's-dollar convention: earnings are indexed to the latest published AWI, the latest bend
points apply to everyone, and projected future earnings count at face value capped at the latest
taxable maximum. Exact for anyone first eligible (age 62) in the formula year or later.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from steward.engine import datafiles
from steward.engine.inputs import Household, Levers, Person

MONTHS_IN_35_YEARS = 420
LATEST_CLAIM_AGE = 70


def fra_months(birth_year: int) -> int:
    """Full retirement age in months: 67 for anyone born 1960 or later."""
    if birth_year >= 1960:
        return 67 * 12
    if birth_year >= 1955:
        return 66 * 12 + 2 * (birth_year - 1954)
    if birth_year >= 1943:
        return 66 * 12
    if birth_year >= 1938:
        return 65 * 12 + 2 * (birth_year - 1937)
    return 65 * 12


def claim_factor(claim_age: int, birth_year: int) -> float:
    c = datafiles.ss_constants()
    fra = fra_months(birth_year)
    months = fra - claim_age * 12
    if months > 0:
        return 1.0 - min(months, 36) * c["early_rate_first_36_months"] - max(months - 36, 0) * c["early_rate_after_36_months"]
    late = min(-months, LATEST_CLAIM_AGE * 12 - fra)
    return 1.0 + late * c["delayed_credit_per_year"] / 12


def spousal_factor(claim_age: int, birth_year: int) -> float:
    c = datafiles.ss_constants()
    months = fra_months(birth_year) - claim_age * 12
    if months > 0:
        return 1.0 - min(months, 36) * c["spousal_early_rate_first_36_months"] - max(months - 36, 0) * c["spousal_early_rate_after_36_months"]
    return 1.0


def aime_cents(earnings_cents: Mapping[int, int], index_year: int) -> int:
    """Average indexed monthly earnings, whole dollars, returned in cents."""
    awi = datafiles.awi()
    base = awi[index_year]
    indexed = [cents * (base / awi[y]) if (y < index_year and y in awi) else float(cents) for y, cents in earnings_cents.items()]
    top35 = sorted(indexed)[-35:]
    return math.floor(sum(top35) / MONTHS_IN_35_YEARS / 100) * 100


def pia_cents(aime: int, formula_year: int) -> int:
    """Primary insurance amount for the formula year, truncated to the next lower dime, in cents."""
    first, second = datafiles.bend_points()[formula_year]
    r1, r2, r3 = datafiles.ss_constants()["pia_rates"]
    a = aime / 100
    pia = r1 * min(a, first) + r2 * max(0.0, min(a, second) - first) + r3 * max(0.0, a - second)
    return math.floor(pia * 10 + 1e-9) * 10


def estimated_record(birth_year: int, salary_cents: int, plan_year: int) -> tuple[tuple[int, int], ...]:
    """Steward's earnings record from today's salary (profile spec P24): each year from the one the person turned 22
    to last year earns salary x AWI(year) / AWI(latest), capped at that year's taxable maximum. Years before the AWI
    file starts are left out; a year after its last counts at the latest AWI (Engineering choice 15)."""
    awi = datafiles.awi()
    cap = datafiles.taxable_max()
    first, latest = min(awi), max(awi)
    out = []
    for year in range(max(birth_year + 22, first), plan_year):
        wage = salary_cents * awi.get(year, awi[latest]) / awi[latest]
        out.append((year, min(math.floor(wage + 0.5), cap[year] * 100)))
    return tuple(out)


def monthly_benefit_cents(pia: int, claim_age: int, birth_year: int) -> int:
    """The worker's own monthly benefit at the claiming age, whole dollars, in cents."""
    return math.floor(pia * claim_factor(claim_age, birth_year) / 100 + 1e-9) * 100


def spousal_benefit_cents(worker_pia: int, claim_age: int, birth_year: int) -> int:
    share = datafiles.ss_constants()["spousal_share"]
    return math.floor(worker_pia * share * spousal_factor(claim_age, birth_year) / 100 + 1e-9) * 100


def person_pia_cents(person: Person, *, start_year: int, yearly_cents: int, stop_age: int) -> int:
    """PIA from the record plus projected years start_year .. birth_year + stop_age - 1."""
    record = dict(person.earnings)
    if yearly_cents > 0:
        cap = datafiles.taxable_max()[datafiles.LATEST_TAXABLE_MAX_YEAR] * 100
        for year in range(start_year, person.birth_year + stop_age):
            record.setdefault(year, min(yearly_cents, cap))
    if not record:
        return 0
    index_year = min(person.birth_year + 60, datafiles.LATEST_AWI_YEAR)
    formula_year = min(person.birth_year + 62, datafiles.LATEST_BEND_YEAR)
    return pia_cents(aime_cents(record, index_year), formula_year)


def jr_pia_by_age(hh: Household, ages: Sequence[int]) -> np.ndarray:
    """Person 1's PIA (cents) for each candidate retirement age: salary years run until they turn that age."""
    return np.array([person_pia_cents(hh.jr, start_year=hh.plan_year, yearly_cents=hh.salary_cents, stop_age=r) for r in ages],
                    dtype=np.int64)


def spouse_pia_cents(hh: Household, levers: Levers) -> int:
    if levers.spouse_earnings_cents > 0 and levers.spouse_start_year > 0:
        return person_pia_cents(hh.spouse, start_year=max(levers.spouse_start_year, hh.plan_year),
                                yearly_cents=levers.spouse_earnings_cents, stop_age=levers.spouse_stop_age)
    return person_pia_cents(hh.spouse, start_year=hh.plan_year, yearly_cents=0, stop_age=0)


def trust_fund_factor(year: int, full_benefits: bool) -> float:
    c = datafiles.ss_constants()
    return 1.0 if full_benefits or year < c["trust_fund_cut_year"] else c["trust_fund_payable"]


@dataclass(frozen=True)
class BenefitSchedule:
    """Monthly amounts in dollars once claimed. Arrays run over candidate retirement ages (A,)."""
    jr_own: np.ndarray
    sp_own: float
    sp_spousal: np.ndarray
    jr_spousal: float


def benefit_schedule(hh: Household, levers: Levers, ages: Sequence[int]) -> BenefitSchedule:
    jr_pia = jr_pia_by_age(hh, ages)
    sp_pia = spouse_pia_cents(hh, levers)
    jr_own = np.array([monthly_benefit_cents(int(p), levers.jr_claim_age, hh.jr.birth_year) for p in jr_pia]) / 100.0
    # A spousal benefit starts only once both have filed, so its reduction counts from the later filing.
    sp_spousal_age = max(levers.spouse_claim_age, levers.jr_claim_age - (hh.spouse.birth_year - hh.jr.birth_year))
    jr_spousal_age = max(levers.jr_claim_age, levers.spouse_claim_age - (hh.jr.birth_year - hh.spouse.birth_year))
    sp_spousal = np.array([spousal_benefit_cents(int(p), sp_spousal_age, hh.spouse.birth_year) for p in jr_pia]) / 100.0
    sp_own = monthly_benefit_cents(sp_pia, levers.spouse_claim_age, hh.spouse.birth_year) / 100.0
    jr_spousal = spousal_benefit_cents(sp_pia, jr_spousal_age, hh.jr.birth_year) / 100.0
    return BenefitSchedule(jr_own=jr_own, sp_own=sp_own, sp_spousal=sp_spousal, jr_spousal=jr_spousal)


def household_benefit(sched: BenefitSchedule, levers: Levers, year: int, jr_age: int, sp_age: int,
                      jr_alive: np.ndarray, sp_alive: np.ndarray) -> np.ndarray:
    """Monthly household benefit in dollars, shape (H, A). jr_alive and sp_alive are (H, 1) bool.

    Each spouse's own benefit starts at their claiming age. Once both have claimed, each takes the
    larger of their own benefit and the spousal benefit. A survivor keeps the larger of the two
    amounts once the survivor has claimed. The trust-fund factor applies from the cut year.
    """
    jr_claimed = jr_age >= levers.jr_claim_age
    sp_claimed = sp_age >= levers.spouse_claim_age
    zero = np.zeros_like(sched.jr_own)
    jr_amt = sched.jr_own if jr_claimed else zero
    sp_amt = np.full_like(sched.jr_own, sched.sp_own) if sp_claimed else zero
    if jr_claimed and sp_claimed:
        jr_amt = np.maximum(jr_amt, sched.jr_spousal)
        sp_amt = np.maximum(sp_amt, sched.sp_spousal)
    larger = np.maximum(jr_amt, sp_amt)
    both = jr_alive & sp_alive
    survivor_claimed = np.where(jr_alive, jr_claimed, sp_claimed)
    one = (jr_alive ^ sp_alive) & survivor_claimed
    total = np.where(both, jr_amt + sp_amt, np.where(one, larger, 0.0))
    return total * trust_fund_factor(year, levers.full_ss_benefits)
