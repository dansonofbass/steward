"""Finding the ages (spec section 3.5) and the result (section 3.7)."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np

from steward.engine import datafiles
from steward.engine.checklist import K401_LIMIT_CENTS
from steward.engine.inputs import EngineInputs, Household, Levers, digest, validate
from steward.engine.levers import clamp
from steward.engine.market import MEAN_BLOCK_YEARS
from steward.engine.simulate import HORIZON_AGE, Prepared, prepare, simulate
from steward.engine.tax import rules
from steward.engine.tax.state import module_for, not_calculated_line, state_name
from steward.engine.version import ENGINE_VERSION

COMFORTABLE = 0.90
ESTIMATE_LINE = ("No earnings record for {person1}: their Social Security is estimated from today's salary, as if their pay had "
                 "followed the national average wage since 22.")
COLLEGE_LINE = ("College: College Board 2025-26 costs for each child's school (tuition and fees, and living costs where "
                "chosen), at the share you plan to cover, growing 1% a year above inflation, for two years from 18 (trade "
                "or community college) or four; the 529 pays first, and 529 contributions continue while {person1} works and "
                "the child is under 18.")
D10_LINE = "The mortgage payment stays the same in dollars, so each year it costs less in today's dollars as prices rise."
D11_LINE = "In retirement, consulting and the spouse's earnings are taxed on one return with withdrawals and Social Security."
LIKELY = 0.80
MAX_RETIRE_AGE = 70


@dataclass(frozen=True)
class BandPoint:
    year: int
    jr_age: int
    p10_cents: int
    p50_cents: int
    p90_cents: int


@dataclass(frozen=True)
class SolveResult:
    comfortable_age: int | None
    likely_age: int | None
    comfortable_year: int | None
    likely_year: int | None
    success_by_age: tuple[tuple[int, float], ...]
    band_age: int | None
    band: tuple[BandPoint, ...]
    assumptions: tuple[str, ...]
    input_digest: str
    engine_version: str
    histories: int
    assumption_groups: tuple[str, ...] = ()   # parallel to assumptions: markets | taxes | ss | lifespans | costs | notice


def candidate_ages(hh: Household) -> list[int]:
    now = hh.plan_year - hh.jr.birth_year
    return list(range(now, MAX_RETIRE_AGE + 1)) if now <= MAX_RETIRE_AGE else []


def first_age(success_by_age: Sequence[tuple[int, float]], threshold: float) -> int | None:
    for age, rate in success_by_age:
        if rate >= threshold:
            return age
    return None


def fractional_age(success_by_age: Sequence[tuple[int, float]], threshold: float) -> float | None:
    """Where the success curve crosses the threshold, interpolated between whole ages."""
    prev = None
    for age, rate in success_by_age:
        if rate >= threshold:
            if prev is None or prev[1] >= threshold:
                return float(age)
            prev_age, prev_rate = prev
            return prev_age + (threshold - prev_rate) / (rate - prev_rate) * (age - prev_age)
        prev = (age, rate)
    return None


def _money(cents: int) -> str:
    return f"${cents // 100:,.0f}"


GROUP_KEYS: tuple[str, ...] = ("markets", "taxes", "ss", "lifespans", "costs", "notice")


def _note_group(note: str) -> str:
    """Where one of plan_inputs' notes goes (Engineering choice 19): the life-table line is a lifespans line and the
    filing approximation a taxes line; the rest (stale balances, default-mix funds) are notices."""
    if note.startswith("Lifespans use"):
        return "lifespans"
    if "filing status is taxed" in note:
        return "taxes"
    return "notice"


def build_assumption_lines(hh: Household, levers: Levers, n_hist: int) -> tuple[tuple[str, str], ...]:
    """Every assumption How it works shows, with the fold it goes in (P29). The words are the plan's own and never
    change here; build_assumptions reads them without the groups."""
    md = datafiles.market()
    ssc = datafiles.ss_constants()
    fed = rules.table("federal", hh.plan_year)
    medicare = rules.table("medicare", hh.plan_year)
    out: list[tuple[str, str]] = [
        (f"Markets: {n_hist:,} histories stitched from US stock, bond and bill returns {int(md.years[0])}–{int(md.years[-1])} "
         f"(Damodaran, downloaded 2026-10-13) in runs averaging {MEAN_BLOCK_YEARS} years; international stocks use the US series.",
         "markets"),
    ]
    if levers.full_ss_benefits:
        out.append(("Full Social Security benefits are assumed (no trust-fund cut).", "ss"))
    else:
        cut = round((1 - ssc["trust_fund_payable"]) * 100)
        out.append((f"Social Security benefits are cut {cut}% from {ssc['trust_fund_cut_year']} ({ssc['report']}).", "ss"))
    out.append((f"Social Security is computed with the {ssc['formula_year']} formula on earnings indexed to the "
                f"{datafiles.LATEST_AWI_YEAR} average wage; future salary counts up to the {datafiles.LATEST_TAXABLE_MAX_YEAR} taxable maximum.", "ss"))
    if hh.jr.estimated:
        out.append((ESTIMATE_LINE, "ss"))
    if not hh.spouse.earnings and not (levers.spouse_earnings_cents and levers.spouse_start_year):
        out.append(("No earnings record for {person2}, who receives the spousal benefit only.", "ss"))
    if min(hh.jr.birth_year, hh.spouse.birth_year) < datafiles.LATEST_BEND_YEAR - 62:
        out.append(("Social Security for someone who turned 62 before 2026 is approximate (no cost-of-living uplift).", "ss"))
    out.append(("Survivors keep the larger benefit, from the year the deceased would have reached their claiming age, "
                "once the survivor has claimed; the spousal top-up starts once both have claimed and is reduced for the age it starts at; "
                "the traditional balance is treated as {person1}'s for required minimum distributions.", "ss"))
    out.append(("Social Security claimed while {person1} is still working, by either spouse, is added to savings and is not taxed.", "ss"))
    if hh.mortgage_payment_cents and hh.mortgage_payoff_year is not None and hh.mortgage_payoff_year >= hh.plan_year:
        out.append((f"The mortgage is paid off in {hh.mortgage_payoff_year}; while {{person1}} still works, the payment is saved from then on.", "costs"))
        out.append((D10_LINE, "costs"))
    out.append((f"401(k) deferrals are capped at the 2026 limit of {_money(K401_LIMIT_CENTS)} (no age-50 catch-up); any excess stays in take-home pay.", "taxes"))
    if hh.state == "CA":
        ca_year = rules.table("california", hh.plan_year).year
        state_text = f" and {ca_year} California rules" + (" (the latest published)" if ca_year < hh.plan_year else "")
    elif module_for(hh.state) is not None:
        state_text = f"; {state_name(hh.state)} has no income tax on wages"
    else:
        state_text = ""
    fed_text = f"{fed.year} federal rules" + (" (the latest published)" if fed.year < hh.plan_year else "")
    out.append((f"Taxes: {fed_text}{state_text}; brackets stay fixed in today's dollars; "
                "half of each taxable-account withdrawal is treated as gain; the tax on a year's withdrawals is estimated from the previous year's; while {person1} works, lever income is taxed on top of their wages.", "taxes"))
    out.append((D11_LINE, "taxes"))
    if module_for(hh.state) is None:
        out.append((not_calculated_line(hh.state), "taxes"))
    if hh.spending_months < 12:
        out.append((f"Based on {hh.spending_months} months of spending history, annualized.", "notice"))
    out.append((f"Health insurance before Medicare: {_money(hh.health_premium_cents)} a year until the older spouse is 65, "
                f"half until the younger is; Medicare Part B ${medicare['part_b_monthly']:,.2f} a month per person from 65.", "costs"))
    if hh.children:
        out.append((COLLEGE_LINE, "costs"))
    out.append((f"Lifespans come from the 2023 Social Security life table; the plan runs until the younger spouse is {HORIZON_AGE} "
                "regardless, and spending does not drop after a death.", "lifespans"))
    out.append(("Retirement spending is met from cash above a one-year buffer, then taxable, traditional, HSA and Roth, after tax; "
                "the house is never sold to fund the plan.", "costs"))
    out.append(("A required minimum distribution beyond the year's need is moved to the taxable bucket after tax. "
                "Retirement income beyond the year's spending is saved to the taxable bucket.", "costs"))
    if hh.default_mix_symbols:
        out.append(("Funds on a default mix (no built-in asset class): " + ", ".join(hh.default_mix_symbols) + ".", "notice"))
    out.extend((n, _note_group(n)) for n in hh.stale_notes)
    return tuple(out)


def build_assumptions(hh: Household, levers: Levers, n_hist: int) -> tuple[str, ...]:
    return tuple(text for text, _ in build_assumption_lines(hh, levers, n_hist))


def solve(inputs: EngineInputs, levers: Levers | None = None, *, ages: Sequence[int] | None = None,
          prepared: Prepared | None = None, band: bool = True) -> SolveResult:
    """band=False leaves out the band (band_age None, band empty) and skips the balances it needs;
    the ages and success rates are the same. lever_impacts uses it, since it reads only the ages."""
    validate(inputs)
    hh = inputs.household
    used = clamp(levers if levers is not None else inputs.levers, hh)
    ages_list = list(ages) if ages is not None else candidate_ages(hh)
    prep = prepared if prepared is not None else prepare(hh)
    n_hist = prep.hist.stock.shape[0]
    lines = build_assumption_lines(hh, used, n_hist)
    assumptions = tuple(t for t, _ in lines)
    groups = tuple(g for _, g in lines)
    input_digest = digest(replace(inputs, levers=used))
    if not ages_list:
        return SolveResult(None, None, None, None, (), None, (), assumptions + ("{person1} is past 70; no retirement ages were tested.",),
                           input_digest, ENGINE_VERSION, n_hist, groups + ("notice",))
    out = simulate(inputs, used, ages_list, prep, track_investable=band)
    rates = out.success.mean(axis=0)
    success_by_age = tuple((age, float(rate)) for age, rate in zip(ages_list, rates))
    comfortable = first_age(success_by_age, COMFORTABLE)
    likely = first_age(success_by_age, LIKELY)
    year_of = lambda age: None if age is None else hh.jr.birth_year + age  # noqa: E731
    if not band:
        return SolveResult(comfortable, likely, year_of(comfortable), year_of(likely), success_by_age, None, (),
                           assumptions, input_digest, ENGINE_VERSION, n_hist, groups)
    band_age = comfortable if comfortable is not None else (likely if likely is not None else ages_list[-1])
    column = ages_list.index(band_age)
    pct = np.percentile(out.investable[:, :, column], [10, 50, 90], axis=1)
    jr_now = hh.plan_year - hh.jr.birth_year
    points = tuple(BandPoint(hh.plan_year + t, jr_now + t, int(round(pct[0, t] * 100)), int(round(pct[1, t] * 100)), int(round(pct[2, t] * 100)))
                 for t in range(pct.shape[1]))
    return SolveResult(comfortable, likely, year_of(comfortable), year_of(likely), success_by_age, band_age, points,
                       assumptions, input_digest, ENGINE_VERSION, n_hist, groups)
