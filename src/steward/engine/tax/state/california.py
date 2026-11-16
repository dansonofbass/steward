"""California (Form 540), from the dated tables in data/rules/california_<year>.json.

California starts from federal AGI, takes Social Security back out, and adds back the HSA deduction and HSA
contributions made through payroll (it doesn't follow the federal HSA rules). It taxes capital gains as ordinary
income and has no QBI deduction. Credits are the personal, age-65 and dependent exemption credits, reduced above the
AGI threshold. The Behavioral Health Services Tax (1% over $1,000,000) is added after credits. For an S-corp it also
gives the franchise tax and SDI on the owner's salary (scorp_costs).
"""
from __future__ import annotations

import math
from datetime import date
from functools import cache

import numpy as np

from steward.engine.tax import rules
from steward.engine.tax.facts import FederalFigures, Installment, StateResult, TaxFacts
from steward.engine.tax.worksheets import schedule_tax, whole


def tax_table_income(ti: int) -> float:
    """The income the 2025 California Tax Table taxes for a taxable income of $100,000 or less: rows $1-$50 (no tax),
    then $100-wide rows centred on each hundred ($51-$150 is taxed at $100), the last row $99,951-$100,000 at $99,975."""
    if ti <= 50:
        return 0.0
    if ti > 99_950:
        return 99_975.0
    return float(((ti + 49) // 100) * 100)


def income_tax(brackets, ti: int, table_up_to: int) -> int:
    """Form 540 line 31: the Tax Table at or below $100,000, the rate schedule above."""
    if ti <= 0:
        return 0
    if ti <= table_up_to:
        return whole(schedule_tax(brackets, tax_table_income(ti)))
    return whole(schedule_tax(brackets, ti))


def exemption_credits(t, filing: str, ages: tuple[int, ...], dependents: int, fed_agi: int) -> int:
    """Form 540 lines 7, 9 and 10, through the AGI Limitation Worksheet when federal AGI is over the threshold."""
    ec, po = t["exemption_credit"], t["credit_phase_out"]
    filers, aged = (2 if filing == "mfj" else 1), sum(1 for a in ages if a >= 65)
    people = filers + aged
    personal = filers * ec["personal"] + aged * ec["age_65"]
    deps = dependents * ec["dependent"]
    over = fed_agi - po["threshold"][filing]
    if over > 0:
        e = math.ceil(over / po["step"]) * po["per_step"]     # worksheet lines c-e
        personal = max(personal - e * people, 0)                # lines f-i
        deps = max(deps - e * dependents, 0)                   # lines j-m
    return personal + deps


class California:
    code = "CA"

    def tax(self, facts: TaxFacts, year: int, fed: FederalFigures) -> StateResult:
        t = rules.table("california", year)
        d = lambda cents: whole(cents / 100)  # noqa: E731
        filing = facts.filing
        ca_agi = fed.agi - fed.taxable_social_security + fed.hsa_deduction + d(facts.payroll_hsa_cents) \
            + d(facts.state_addback_cents)
        medical = max(d(facts.medical_cents) - whole(fed.agi * t["medical_floor"]), 0)
        others = d(facts.property_tax_cents) + d(facts.mortgage_interest_cents) + d(facts.charity_cents)
        itemized = medical + others
        lim = t["itemized_limit"]
        if fed.agi > lim["threshold"][filing] and others > 0:     # Schedule CA line 29 worksheet
            itemized -= min(whole(others * lim["itemized_rate"]), whole((fed.agi - lim["threshold"][filing]) * lim["agi_rate"]))
        standard = t["standard_deduction"][filing]
        deduction = max(standard, itemized)
        ti = max(ca_agi - deduction, 0)
        tax = income_tax(t["brackets"][filing], ti, t["tax_table_up_to"])
        credits = min(exemption_credits(t, filing, facts.ages, len(facts.dependents), fed.agi), tax)
        bhs = t["behavioral_health_tax"]
        surtax = whole(max(ti - bhs["over"], 0) * bhs["rate"])
        lines = []
        if t.year < year:
            lines.append(f"Using {t.year} California rules (the latest published).")
        if itemized > standard:
            lines.append(f"California itemized deductions of ${itemized:,} were more than the ${standard:,} standard deduction.")
        if surtax:
            lines.append(f"California's 1% tax on income over $1,000,000 adds ${surtax:,}.")
        return StateResult(state="CA", calculated=True, tax_cents=(tax - credits + surtax) * 100, agi_cents=ca_agi * 100,
                           taxable_income_cents=ti * 100, credits_cents=credits * 100, rules_year=t.year,
                           explain=tuple(lines))

    def scorp_costs(self, salary_cents: int, net_income_cents: int, year: int):
        """The 1.5% S-corp franchise tax on net income, at least the $800 minimum, and SDI withheld from the
        owner's salary (no wage limit since 2024), from california_business_<year>.json."""
        from steward.engine.tax.state import ScorpStateCosts
        t = rules.table("california_business", year)
        # Employer UI (the new-employer rate) and ETT on the first $7,000 of the owner's wages; a business expense,
        # so it comes out of the net income the franchise tax is figured on.
        unemployment = round(min(max(salary_cents, 0), t["ui_ett_wage_limit"] * 100) * (t["new_employer_ui_rate"] + t["ett_rate"]))
        franchise = max(round(max(net_income_cents - unemployment, 0) * t["scorp_franchise_rate"]), t["minimum_franchise_tax"] * 100)
        sdi_wages = max(salary_cents, 0)
        if t["sdi_wage_limit"] is not None:
            sdi_wages = min(sdi_wages, t["sdi_wage_limit"] * 100)
        lines = (f"Using {t.year} California business rules (the latest published).",) if t.year < year else ()
        return ScorpStateCosts(state="CA", calculated=True, franchise_cents=franchise, unemployment_cents=unemployment,
                               sdi_cents=round(sdi_wages * t["sdi_rate"]), rules_year=t.year, explain=lines)

    def estimates_schedule(self, year: int) -> tuple[Installment, ...]:
        e = rules.table("california", year)["estimates"]
        out = []
        for share, due in zip(e["shares"], e["due"]):
            month, day = (int(x) for x in due.split("-"))
            out.append(Installment(due=date(year + 1 if month == 1 else year, month, day), share=share))
        return tuple(out)

    def vector_tax(self, income: np.ndarray, fed_agi: np.ndarray, filing: str, n_aged: int, year: int) -> np.ndarray:
        """California tax for the plan on `income` (federal AGI less Social Security): the
        standard deduction, the rate schedule, the personal and age-65 credits, then the 1% tax over $1,000,000.
        Neither input array is changed."""
        v = _vec(year, filing)
        taxable = income - v.standard
        np.maximum(taxable, 0.0, out=taxable)
        tax = np.interp(taxable, v.lower, v.cum)
        if taxable.size and taxable.max() > v.lower[-1]:
            tax += np.maximum(taxable - v.lower[-1], 0.0) * v.top_rate
        people = v.filers + n_aged
        credit = v.filers * v.personal + n_aged * v.age_65
        if fed_agi.size and fed_agi.max() > v.phase_out_threshold:
            steps = np.ceil(np.maximum(fed_agi - v.phase_out_threshold, 0.0) / v.step)
            tax -= np.maximum(credit - steps * v.per_step * people, 0.0)
        else:
            tax -= credit
        np.maximum(tax, 0.0, out=tax)
        if taxable.size and taxable.max() > v.surtax_over:
            tax += v.surtax_rate * np.maximum(taxable - v.surtax_over, 0.0)
        return tax


class _Vec:
    def __init__(self, t, filing: str):
        rows = t["brackets"][filing]
        self.lower = np.array([float(r[0]) for r in rows])
        rate = np.array([float(r[1]) for r in rows])
        self.cum = np.concatenate([[0.0], np.cumsum(rate[:-1] * np.diff(self.lower))])
        self.top_rate = float(rate[-1])
        self.standard = float(t["standard_deduction"][filing])
        self.surtax_over = float(t["behavioral_health_tax"]["over"])
        self.surtax_rate = float(t["behavioral_health_tax"]["rate"])
        self.filers = 2 if filing == "mfj" else 1
        self.personal = float(t["exemption_credit"]["personal"])
        self.age_65 = float(t["exemption_credit"]["age_65"])
        po = t["credit_phase_out"]
        self.phase_out_threshold = float(po["threshold"][filing])
        self.step = float(po["step"])
        self.per_step = float(po["per_step"])


@cache
def _vec(year: int, filing: str) -> _Vec:
    return _Vec(rules.table("california", year), filing)


MODULE = California()
