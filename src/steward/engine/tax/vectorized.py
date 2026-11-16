"""The Monte Carlo plan's tax, vectorized over numpy arrays of dollars (spec 3.1, 3.5), driven from the same dated
tables as annual_tax.

It covers what the plan's returns contain: ordinary income (withdrawals, wages, lever income), long-term gains stacked
on top, the Social Security worksheet, the standard deduction with the amount for each person 65 and over, the
deduction for people 65 and over while it lasts (through 2028), the 3.8% tax on investment income, and the state
module's vector path. It skips what annual_tax does that the plan never has: itemizing, credits, self-employment tax
on the return (levers handle their own), QBI and the Tax Table's $50 rows. tests/engine/test_tax_parity.py holds it
within $50 of annual_tax on a grid of incomes, filing statuses and ages.

Brackets stay fixed after the last published year because the engine runs in today's dollars.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cache

import numpy as np

from steward.engine.inputs import Household, Levers
from steward.engine.tax import rules
from steward.engine.tax.state import module_for


@dataclass(frozen=True)
class Schedule:
    lower: np.ndarray   # bracket floors; the first is 0
    rate: np.ndarray    # marginal rate in each bracket
    cum: np.ndarray     # tax owed at each floor


def make_schedule(rows) -> Schedule:
    lower = np.array([float(r[0]) for r in rows])
    rate = np.array([float(r[1]) for r in rows])
    cum = np.concatenate([[0.0], np.cumsum(rate[:-1] * np.diff(lower))])
    return Schedule(lower=lower, rate=rate, cum=cum)


@dataclass(frozen=True)
class VecRules:
    """One year's federal numbers for one filing status, as floats."""
    rules_year: int
    schedule: Schedule
    standard: float
    aged: float
    zero_max: float
    fifteen_max: float
    ss_base: float
    ss_upper: float
    over_65: tuple[float, float, float] | None   # (amount, threshold, rate), or None once it has ended
    niit_rate: float
    niit_threshold: float


@cache
def vec_rules(year: int, filing: str) -> VecRules:
    F = rules.table("federal", year)
    o65 = F["over_65_deduction"]
    return VecRules(
        rules_year=F.year, schedule=make_schedule(F["brackets"][filing]),
        standard=float(F["standard_deduction"][filing]), aged=float(F["aged_additional"][filing]),
        zero_max=float(F["ltcg"][filing][0]), fifteen_max=float(F["ltcg"][filing][1]),
        ss_base=float(F["ss_thresholds"][filing][0]), ss_upper=float(F["ss_thresholds"][filing][1]),
        over_65=(float(o65["amount"]), float(o65["threshold"][filing]), float(o65["rate"])) if year <= o65["last_year"] else None,
        niit_rate=float(F["niit"]["rate"]), niit_threshold=float(F["niit"]["threshold"][filing]),
    )


def tax_on(schedule: Schedule, income) -> np.ndarray:
    """Progressive tax is piecewise linear in income, so interpolate the cumulative table."""
    x = np.maximum(np.asarray(income, dtype=float), 0.0)
    return np.interp(x, schedule.lower, schedule.cum) + np.maximum(x - schedule.lower[-1], 0.0) * schedule.rate[-1]


def ltcg_tax(ordinary_taxable, gains, v: VecRules) -> np.ndarray:
    """Long-term gains stacked on top of ordinary taxable income: 0%, 15%, then 20%."""
    o = np.asarray(ordinary_taxable, dtype=float)
    total = o + np.asarray(gains, dtype=float)
    at15 = np.maximum(np.minimum(total, v.fifteen_max) - np.maximum(o, v.zero_max), 0.0)
    at20 = np.maximum(total - np.maximum(o, v.fifteen_max), 0.0)
    return 0.15 * at15 + 0.20 * at20


def taxable_social_security(benefits, other_income, v: VecRules) -> np.ndarray:
    """The part of Social Security that is taxable (Publication 915 Worksheet 1 with no adjustments)."""
    b = np.asarray(benefits, dtype=float)
    provisional = np.asarray(other_income, dtype=float) + 0.5 * b
    tier1 = np.minimum(0.5 * np.clip(provisional - v.ss_base, 0.0, v.ss_upper - v.ss_base), 0.5 * b)
    tier2 = 0.85 * np.maximum(provisional - v.ss_upper, 0.0)
    return np.minimum(0.85 * b, tier1 + tier2)


def over_65_deduction(agi, n_aged: int, v: VecRules):
    """Schedule 1-A Part V for `n_aged` people: $6,000 each less 6% of MAGI over the threshold; 0 once it has ended."""
    if not n_aged or v.over_65 is None:
        return 0.0
    amount, threshold, rate = v.over_65
    return n_aged * np.maximum(amount - rate * np.maximum(np.asarray(agi, dtype=float) - threshold, 0.0), 0.0)


def household_tax(ordinary, gains, social_security, filing: str, state: str, n_aged: int, year: int) -> np.ndarray:
    """Federal plus state tax for one year. The deduction comes off ordinary income first; gains stack on top. The
    net investment income tax applies to the gains above its threshold. The state taxes ordinary income and gains
    and, in California, leaves Social Security alone.

    This is the simulation's hot path: in-place operations, and terms that are exactly zero are skipped. The result
    equals composing taxable_social_security, over_65_deduction, tax_on, ltcg_tax and the state's vector_tax
    (tests/engine/test_vectorized.py checks it bit for bit).
    """
    v = vec_rules(year, filing)
    o, g, b = (np.asarray(x, dtype=float) for x in (ordinary, gains, social_security))
    scalar = o.ndim == g.ndim == b.ndim == 0
    if scalar:                                     # numpy hands back scalars, not arrays, for 0-d arithmetic
        o, g, b = o.reshape(1), g.reshape(1), b.reshape(1)
    og = o + g                                     # used by the Social Security test, AGI and the state
    if b.any():                                    # nothing claimed yet, nothing to test
        agi = _taxable_ss_into(b, og, v)
        agi += og
    else:
        agi = og                                   # read-only from here on
    deduction = v.standard + n_aged * v.aged
    if n_aged and v.over_65 is not None:
        tt = agi - over_65_deduction(agi, n_aged, v)
        tt -= deduction
    else:
        tt = agi - deduction
    np.maximum(tt, 0.0, out=tt)                    # taxable income
    gains_taxable = np.minimum(g, tt)
    ordinary_taxable = np.subtract(tt, gains_taxable, out=tt)   # never negative, since gains_taxable <= tt
    total = _tax_on_nonnegative(v.schedule, ordinary_taxable)
    if gains_taxable.any():                        # with no gains the stacked tax is exactly 0
        total += _ltcg_into(ordinary_taxable, gains_taxable, v)
        if agi.size and agi.max() > v.niit_threshold:
            total += v.niit_rate * np.minimum(g, np.maximum(agi - v.niit_threshold, 0.0))
    mod = module_for(state)
    if mod is not None:
        total += mod.vector_tax(og, agi, filing, n_aged, year)
    return total[0] if scalar else total           # a numpy scalar for scalar inputs


def _tax_on_nonnegative(schedule: Schedule, x: np.ndarray) -> np.ndarray:
    """tax_on for income already known to be >= 0; the top-bracket term is added only where it is non-zero."""
    out = np.interp(x, schedule.lower, schedule.cum)
    top = schedule.lower[-1]
    if x.size and x.max() > top:
        out += np.maximum(x - top, 0.0) * schedule.rate[-1]
    return out


def _taxable_ss_into(b: np.ndarray, other_income: np.ndarray, v: VecRules) -> np.ndarray:
    """taxable_social_security, in a fresh array of the broadcast shape."""
    half_b = 0.5 * b
    provisional = other_income + half_b
    tier1 = provisional - v.ss_base
    np.clip(tier1, 0.0, v.ss_upper - v.ss_base, out=tier1)
    tier1 *= 0.5
    np.minimum(tier1, half_b, out=tier1)
    provisional -= v.ss_upper                      # provisional now holds tier 2
    np.maximum(provisional, 0.0, out=provisional)
    provisional *= 0.85
    tier1 += provisional
    np.multiply(b, 0.85, out=provisional)
    return np.minimum(provisional, tier1, out=tier1)


def _ltcg_into(o: np.ndarray, g: np.ndarray, v: VecRules) -> np.ndarray:
    """ltcg_tax, in a fresh array."""
    total = o + g
    at15 = np.minimum(total, v.fifteen_max)
    floor = np.maximum(o, v.zero_max)
    at15 -= floor
    np.maximum(at15, 0.0, out=at15)
    np.maximum(o, v.fifteen_max, out=floor)
    total -= floor                                 # total now holds the part at 20%
    np.maximum(total, 0.0, out=total)
    at15 *= 0.15
    total *= 0.20
    at15 += total
    return at15


def se_tax(net_profit: float, w2_wages: float, year: int) -> tuple[float, float]:
    """Self-employment tax and its deductible half (Schedule SE, to the cent). OASDI applies only to the wage base
    left after W-2 wages."""
    P = rules.table("payroll", year)
    se = P["se"]
    base = max(net_profit, 0.0) * se["net_factor"]
    if base < se["minimum_net_earnings"]:
        return 0.0, 0.0
    oasdi = se["oasdi_rate"] * max(min(base, P["wage_base"] - w2_wages), 0.0)
    tax = oasdi + se["medicare_rate"] * base
    return tax, tax / 2


def employee_fica_rate(year: int) -> float:
    e = rules.table("payroll", year)["employee"]
    return e["oasdi_rate"] + e["medicare_rate"]


@dataclass(frozen=True)
class LeverIncome:
    """One year of lever income: cash is what arrives after self-employment tax and the employee's FICA; ordinary is
    what joins the return's ordinary income (consulting less half its SE tax, plus the spouse's earnings). The gift
    is cash but not income."""
    cash: float
    ordinary: float


def lever_income(hh: Household, levers: Levers, year: int, jr_age: int, sp_age: int, w2_wages: float) -> LeverIncome:
    consulting = levers.consulting_cents / 100 if (levers.consulting_cents and jr_age < levers.consulting_until_age) else 0.0
    gift = levers.gift_cents / 100 if (levers.gift_cents and year <= levers.gift_until_year) else 0.0
    spouse_on = (levers.spouse_earnings_cents and levers.spouse_start_year
                 and year >= levers.spouse_start_year and sp_age < levers.spouse_stop_age)
    spouse = levers.spouse_earnings_cents / 100 if spouse_on else 0.0
    if consulting == 0.0 and spouse == 0.0:
        return LeverIncome(cash=gift, ordinary=0.0)
    se, se_half = se_tax(consulting, w2_wages, year)
    fica = employee_fica_rate(year) * spouse
    return LeverIncome(cash=consulting + spouse + gift - se - fica, ordinary=consulting + spouse - se_half)


def lever_income_after_tax(hh: Household, levers: Levers, year: int, jr_age: int, sp_age: int, base_wages: float) -> float:
    """While Person 1 works: lever income after the extra tax it causes on top of their wages.

    base_wages is the taxable wage income already on the return (salary less the pre-tax 401(k) deferral). SE tax's
    OASDI part counts gross salary (deferrals included) against the wage base. In retirement the plan puts
    lever_income(...).ordinary on the return itself (D11) instead of calling this."""
    # Only the business owner's own wages use up the wage base: Person 1's when they run the business, none when Person 2 does.
    gross_wages = hh.salary_cents / 100 if base_wages > 0 and hh.business_owner == 0 else 0.0
    li = lever_income(hh, levers, year, jr_age, sp_age, gross_wages)
    if li.ordinary == 0.0:
        return li.cash
    before = household_tax(base_wages, 0.0, 0.0, hh.filing_status, hh.state, 0, year)
    after = household_tax(base_wages + li.ordinary, 0.0, 0.0, hh.filing_status, hh.state, 0, year)
    return float(li.cash - (after - before))
