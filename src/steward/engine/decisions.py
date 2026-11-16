"""Tax decisions shared by Next dollar (cash-flow and tax spec section 6) and part 5 (section 7).

Part 4 builds the minimal versions; part 5 refines them in place, keeping these names and signatures:

- retirement_choice(now, later, year): pre-tax or Roth, from annual_tax's marginal rate this year against the rate
  expected later. Part 4's later_facts_estimate treats all of today's spending as traditional withdrawals from 67, an
  upper bound on the later rate; part 5 replaces it with the projection's retirement years (RMDs and taxed Social
  Security included).
- business_plan_room(...): a Solo 401(k)'s room for a sole proprietor. Part 5 adds the SEP and the deadlines.

Part 5 (tax decisions plan Task 3) adds self_employed_room (Publication 560's worksheet, SEP and Solo 401(k) side by
side), a rate_later option on retirement_choice for the projection's rate in retirement, choice_line, and
conversion_room. Part 4's business_plan_room stays for Next dollar; a test keeps the two close (the worksheet is a
little lower only when a large own part meets a small profit).

Limits come from data/rules/retirement_<year>.json (2026: IRS Notice 2025-67; Rev. Proc. 2025-19; 26 U.S.C. 223(b)(3);
26 U.S.C. 404(h) and 402(h)). Each function that reads a limit returns the table year it used, so the screen can say
"2026 limits" even in 2027."""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cache
from typing import Literal

import numpy as np

from steward.engine import datafiles
from steward.engine.inputs import InputError, Mix
from steward.engine.market import real_returns
from steward.engine.tax import annual_tax, rules
from steward.engine.tax.facts import TaxFacts, TaxResult
from steward.engine.tax.worksheets import whole

Lean = Literal["pretax", "roth"]
LATER_AGE = 67                  # the age the later estimate starts from
LEAN_MARGIN = 0.02              # rates within 2 points of each other: "about the same" (tax decisions ruling 17)
MIN_CONVERSION_CENTS = 100_000  # a conversion under $1,000 isn't worth a line (ruling 18)


@dataclass(frozen=True)
class RetirementChoice:
    lean: Lean                  # "pretax": the business plan (or a traditional account) saves more; "roth": a Roth does
    now_rate: float             # federal and state tax on the next $100 of ordinary income this year
    later_rate: float           # the same in retirement: the later facts' rate, or the projection's (rate_later)
    rules_year: int             # the federal rules used
    about_same: bool = False    # within LEAN_MARGIN: either works (part 5)
    line: str = ""              # "Roth this year: 12% now against about 22% later." (spec 7.3)


def _pct(rate: float) -> str:
    return f"{round(rate * 100)}%"


def _usd(cents: int) -> str:
    return f"${round(cents / 100):,}"


def choice_line(now_rate: float, later_rate: float) -> str:
    """Spec 7.3's lean with the numbers."""
    rates = f"{_pct(now_rate)} now against about {_pct(later_rate)} later."
    if abs(now_rate - later_rate) <= LEAN_MARGIN:
        return f"About the same: {rates} Either works."
    return f"Roth this year: {rates}" if later_rate >= now_rate else f"Traditional this year: {rates}"


def retirement_choice(now: TaxFacts, later: TaxFacts | None, year: int, *,
                      rate_later: float | None = None) -> RetirementChoice:
    """Pre-tax saves more when this year's marginal rate is higher than the later one; a tie leans Roth (part 4).
    rate_later (part 5: the projection's median marginal rate over the first ten years of required withdrawals)
    replaces the later facts' rate when given; `later` may then be None."""
    a = annual_tax(now, year)
    if rate_later is None:
        if later is None:
            raise InputError("Give a later year or its rate.")
        rate_later = annual_tax(later, year).marginal_rate
    lean: Lean = "pretax" if a.marginal_rate > rate_later else "roth"
    return RetirementChoice(lean, a.marginal_rate, rate_later, a.rules_year,
                            about_same=abs(a.marginal_rate - rate_later) <= LEAN_MARGIN,
                            line=choice_line(a.marginal_rate, rate_later))


def later_facts_estimate(now: TaxFacts, spending_cents: int) -> TaxFacts:
    """A retirement year in today's dollars: the same filing and state, each adult at least LATER_AGE, and today's
    yearly spending drawn from traditional accounts."""
    return TaxFacts(filing=now.filing, ages=tuple(max(a, LATER_AGE) for a in now.ages), state=now.state,
                    ira_distributions_cents=max(0, spending_cents))


def k401_catch_up_cents(age: int, year: int) -> int:
    """The 401(k) catch-up at this age on December 31: the larger one from 60 to 63, the usual one from 50."""
    t = rules.table("retirement", year)
    if 60 <= age <= 63:
        return t["k401_catch_up_60_to_63"] * 100
    return t["k401_catch_up_50"] * 100 if age >= 50 else 0


def k401_limit_cents(age: int, year: int) -> int:
    """One person's 401(k) employee deferral limit for the year at this age on December 31, catch-up included."""
    return rules.table("retirement", year)["k401_deferral"] * 100 + k401_catch_up_cents(age, year)


def ira_limit_cents(age: int, year: int) -> int:
    """One person's IRA limit for the year, traditional and Roth together, with the catch-up from 50."""
    t = rules.table("retirement", year)
    return (t["ira"] + (t["ira_catch_up_50"] if age >= 50 else 0)) * 100


def business_plan_room(profit_cents: int, se_tax_cents: int, w2_deferral_cents: int, age: int,
                       year: int) -> tuple[int, int]:
    """A sole proprietor's Solo 401(k) room for the year: the employer part (20% of net self-employment earnings,
    which are profit less half the self-employment tax, on compensation up to the cap) plus the employee deferral left
    after any W-2 401(k) deferrals, within net earnings and the overall cap; the catch-up goes on top."""
    t = rules.table("retirement", year)
    net = max(0, profit_cents - se_tax_cents // 2)
    employer = round(min(net, t["compensation_cap"] * 100) * t["self_employed_employer_rate"])
    left = max(0, net - employer)
    base = min(max(0, t["k401_deferral"] * 100 - w2_deferral_cents), left)
    catch = min(k401_catch_up_cents(age, year), left - base)
    return min(t["overall_cap"] * 100, employer + base) + catch, t.year


def roth_ira_limit(magi_cents: int, filing: str, age: int, year: int) -> tuple[int, int]:
    """One person's Roth IRA limit at this income (IRS Publication 590-A worksheet 2-2): the full limit up to the
    phase-out's start, nothing from its end, and in between the share left, rounded up to the next $10 and never under
    $200. The household's earned income caps the total; Task 3 applies that."""
    t = rules.table("retirement", year)
    full = ira_limit_cents(age, year)
    lo, hi = (x * 100 for x in t["roth_ira_phaseout"]["mfj" if filing == "mfj" else "single"])
    if magi_cents <= lo:
        return full, t.year
    if magi_cents >= hi:
        return 0, t.year
    num, den = full * (hi - magi_cents), (hi - lo) * 1_000
    reduced = -(-num // den) * 1_000            # round up to the next $10, in whole numbers
    return max(reduced, 20_000), t.year


def hsa_limit(family: bool, ages: tuple[int, ...], year: int) -> tuple[int, int]:
    """The household's HSA limit: family or self-only coverage, plus the catch-up for each adult 55 or older."""
    t = rules.table("retirement", year)
    h = t["hsa"]
    base = h["family" if family else "self_only"]
    return (base + h["catch_up_55"] * sum(1 for a in ages if a >= 55)) * 100, t.year


@cache
def expected_real_return(mix: Mix) -> float:
    """The mix's long-run yearly growth above inflation: the compound (geometric) mean of the market history the plan
    samples from, less the fund fees."""
    rr = real_returns(datafiles.market())
    series = mix.stock * rr.stock + mix.bond * rr.bond + mix.cash * rr.cash - mix.fee_bp / 10_000
    return float(np.exp(np.mean(np.log1p(series))) - 1.0)


@dataclass(frozen=True)
class SelfEmployedRoom:
    """Cents. sep_cents is a SEP's most; the solo_* fields are a Solo 401(k)'s parts and its total."""
    net_earnings_cents: int      # step 3: profit less the deductible half of self-employment tax
    sep_cents: int               # the smaller of step 7 and step 8
    solo_own_cents: int          # step 15: the owner's own deferral
    solo_business_cents: int     # step 13: the business's part
    solo_catch_up_cents: int     # step 18
    solo_total_cents: int        # step 19
    deferral_limit_cents: int    # the year's own-part limit, catch-up not included
    used_elsewhere_cents: int    # W-2 deferrals counted against it
    rules_year: int


def self_employed_room(profit: int, se_half: int, *, age: int, w2_deferrals: int, year: int,
                       plan_rate: float | None = None, employer_rate: float | None = None) -> SelfEmployedRoom:
    """IRS Publication 560's Deduction Worksheet for Self-Employed, steps 3-19, in whole dollars: Schedule C profit,
    the deductible half of self-employment tax, the owner's age at the end of the year, and the owner's W-2 401(k)
    deferrals this year (they use the same yearly own-part limit, section 402(g)). plan_rate and employer_rate default
    to the table's 25% and 20% (the Rate Table for Self-Employed); the publication's own example passes 8.5% and 0.078."""
    r = rules.table("retirement", year)
    plan = r["sep_rate"] if plan_rate is None else plan_rate
    rate = r["self_employed_employer_rate"] if employer_rate is None else employer_rate
    step3 = max(profit - se_half, 0)
    step5 = whole(step3 * rate)
    step6 = whole(r["compensation_cap"] * plan)
    step7 = min(step5, step6)
    step8 = r["overall_cap"]
    sep = min(step7, step8)
    limit = r["k401_deferral"]
    used = max(w2_deferrals, 0)
    step9 = min(max(limit - used, 0), step3)
    step10 = step8 - step9
    step11 = step3 - step9
    step12 = whole(step11 / 2)
    step13 = min(step7, step10, step12)
    step14 = step3 - step13
    step15 = min(step9, step14)
    step16 = step14 - step15
    step17 = max(k401_catch_up_cents(age, year) // 100 - max(used - limit, 0), 0)
    step18 = min(step16, step17)
    step19 = step13 + step15 + step18
    return SelfEmployedRoom(net_earnings_cents=step3 * 100, sep_cents=sep * 100, solo_own_cents=step15 * 100,
                            solo_business_cents=step13 * 100, solo_catch_up_cents=step18 * 100,
                            solo_total_cents=step19 * 100, deferral_limit_cents=limit * 100,
                            used_elsewhere_cents=min(used, limit) * 100, rules_year=r.year)


@dataclass(frozen=True)
class Conversion:
    amount_cents: int
    tax_cents: int
    bracket_rate: float
    line: str


def conversion_room(facts: TaxFacts, year: int, result: TaxResult, *, traditional_cents: int,
                    rate_later: float | None) -> Conversion | None:
    """`result` is annual_tax(facts, year) with its marginal rate. None unless this year's marginal rate is more than
    LEAN_MARGIN below rate_later and at least MIN_CONVERSION_CENTS of traditional money fits in this year's federal
    bracket. Steward never moves money."""
    if rate_later is None or traditional_cents < MIN_CONVERSION_CENTS:
        return None
    if result.marginal_rate + LEAN_MARGIN >= rate_later:
        return None
    brackets = rules.table("federal", year)["brackets"][facts.filing]
    ti = result.taxable_income_cents // 100
    above = [lo for lo, _ in brackets if lo > ti]
    if not above:
        return None
    rate = [rt for lo, rt in brackets if lo <= ti][-1]
    amount = min((above[0] - ti) * 100, traditional_cents)
    if amount < MIN_CONVERSION_CENTS:
        return None
    converted = replace(facts, ira_distributions_cents=facts.ira_distributions_cents + amount)
    cost = annual_tax(converted, year, marginal=False).total_tax_cents - result.total_tax_cents
    line = (f"This year's rate is low: converting {_usd(amount)} of traditional money to Roth would cost about "
            f"{_usd(cost)} in tax, filling the {_pct(rate)} federal bracket ({result.rules_year} rules).")
    return Conversion(amount, cost, rate, line)
