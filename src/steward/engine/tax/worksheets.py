"""The IRS worksheets annual_tax follows, line by line, in whole dollars (forms let you round to dollars; these do).

Each function names the form and lines it follows. Inputs are whole dollars; results are whole dollars, rounded half
up as the forms do. Nothing here reads a rule table: the caller passes the numbers.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

Brackets = Sequence[Sequence[float]]   # [[floor, rate], ...], the first floor 0


def whole(x: float) -> int:
    """Round half up to whole dollars, as the forms do ($2,800.50 is $2,801). Negative amounts round symmetrically."""
    return int(math.floor(abs(x) + 0.5 + 1e-9)) * (1 if x >= 0 else -1)


def schedule_tax(brackets: Brackets, income: float) -> float:
    """Tax from a rate schedule, to the cent (not rounded)."""
    x = max(float(income), 0.0)
    tax = 0.0
    for i, (floor, rate) in enumerate(brackets):
        top = brackets[i + 1][0] if i + 1 < len(brackets) else math.inf
        if x <= floor:
            break
        tax += (min(x, top) - floor) * rate
    return round(tax, 2)


def federal_tax_table_income(ti: int) -> float:
    """The income the 2025 Form 1040 Tax Table taxes for a taxable income under $100,000: the middle of its row.
    Rows: under $5 is $0; $5-$15 and $15-$25; $25-wide rows to $3,000; $50-wide rows to $100,000 ("at least, but less than")."""
    if ti < 5:
        return 0.0
    if ti < 15:
        return 10.0
    if ti < 25:
        return 20.0
    if ti < 3000:
        return (ti // 25) * 25 + 12.5
    return (ti // 50) * 50 + 25.0


def federal_income_tax(brackets: Brackets, ti: int) -> int:
    """Form 1040 line 16 for ordinary income: the Tax Table under $100,000, the Tax Computation Worksheet above."""
    if ti <= 0:
        return 0
    if ti < 100_000:
        return whole(schedule_tax(brackets, federal_tax_table_income(ti)))
    return whole(schedule_tax(brackets, ti))


def qualified_dividends_and_capital_gain_tax(brackets: Brackets, ltcg_bounds: Sequence[float], ti: int,
                                             qualified_dividends: int, net_capital_gain: int) -> tuple[int, int]:
    """Form 1040 Qualified Dividends and Capital Gain Tax Worksheet (2025), lines 1-25.

    Returns (tax on the ordinary part, tax on the qualified dividends and gains); their sum is line 25. When line 24
    (the regular tax on all of it) is smaller, the whole amount is the ordinary part."""
    zero_max, fifteen_max = ltcg_bounds
    l1 = ti
    l4 = qualified_dividends + max(net_capital_gain, 0)
    l5 = max(l1 - l4, 0)
    l7 = min(l1, zero_max)
    l8 = min(l5, l7)
    l9 = l7 - l8                          # taxed at 0%
    l10 = min(l1, l4)
    l12 = l10 - l9
    l14 = min(l1, fifteen_max)
    l15 = l5 + l9
    l16 = max(l14 - l15, 0)
    l17 = min(l12, l16)
    l18 = whole(l17 * 0.15)
    l19 = l9 + l17
    l20 = l10 - l19
    l21 = whole(l20 * 0.20)
    l22 = federal_income_tax(brackets, l5)
    l23 = l18 + l21 + l22
    l24 = federal_income_tax(brackets, l1)
    if l24 <= l23:
        return l24, 0
    return l22, l18 + l21


def taxable_social_security(benefits: int, other_income: int, tax_exempt_interest: int, adjustments: int,
                            thresholds: Sequence[int]) -> int:
    """Publication 915 (2025) Worksheet 1, lines 1-19. `other_income` is line 3 (Form 1040 lines 1z, 2b, 3b, 4b, 5b,
    7a and 8); `adjustments` is line 7 (Schedule 1 lines 11-20, 23 and 25); thresholds are line 9 and line 9 + line 11."""
    if benefits <= 0:
        return 0
    base, upper = thresholds
    l1 = benefits
    l2 = l1 * 0.5
    l6 = l2 + other_income + tax_exempt_interest
    if adjustments >= l6:
        return 0
    l8 = l6 - adjustments
    if l8 <= base:
        return 0
    l10 = l8 - base
    l11 = upper - base
    l12 = max(l10 - l11, 0)
    l13 = min(l10, l11)
    l14 = l13 * 0.5
    l15 = min(l2, l14)
    l16 = l12 * 0.85
    l17 = l15 + l16
    l18 = l1 * 0.85
    return whole(min(l17, l18))


def schedule_se(profit: int, payroll_wages: int, wage_base: int, net_factor: float, oasdi_rate: float,
                medicare_rate: float, minimum_net_earnings: int) -> tuple[int, int, float]:
    """Schedule SE (2025) Part I, lines 2-13: (self-employment tax, its deductible half, net earnings on line 4a/6).
    Line 8d's wages count against the Social Security wage base."""
    net = profit * net_factor                                    # line 4a (and 6)
    if net < minimum_net_earnings:                               # line 4c: under $400, no tax
        return 0, 0, max(net, 0.0)
    l9 = max(wage_base - payroll_wages, 0)
    l10 = min(net, l9) * oasdi_rate
    l11 = net * medicare_rate
    l12 = whole(l10 + l11)
    return l12, whole(l12 * 0.5), net


def additional_medicare_tax(payroll_wages: int, se_net_earnings: float, threshold: int, rate: float) -> int:
    """Form 8959 Parts I and II: 0.9% of Medicare wages over the threshold, then of self-employment earnings over
    what the wages left of it."""
    part1 = max(payroll_wages - threshold, 0) * rate
    part2 = max(max(se_net_earnings, 0.0) - max(threshold - payroll_wages, 0), 0) * rate
    return whole(part1 + part2)


def qbi_deduction(qbi: int, w2_wages: int, sstb: bool, ti_before_qbi: int, net_capital_gain: int, *, rate: float,
                  threshold: int, phase_in: int, wage_limit_rate: float, minimum_deduction: int, minimum_qbi: int) -> int:
    """The qualified business income deduction for one business with no business property (UBIA).

    At or below the threshold, Form 8995 lines 2-15: 20% of QBI, limited to 20% of taxable income less net capital
    gain. Above it, Form 8995-A Parts II and III: a specified service business keeps the applicable percentage of its
    QBI and wages, and the wage limit (50% of W-2 wages) phases in over the range. From 2026, a business with at least
    $1,000 of QBI gets at least $400 (section 199A(i))."""
    if qbi <= 0:
        return 0
    over = ti_before_qbi - threshold
    keep = 1.0                                   # the share of a specified service business's QBI that still counts
    if over <= 0:
        component = qbi * rate
    elif over >= phase_in:
        keep = 0.0 if sstb else 1.0
        component = 0.0 if sstb else min(qbi * rate, w2_wages * wage_limit_rate)
    else:
        frac = over / phase_in
        keep = 1.0 - frac if sstb else 1.0
        full = qbi * keep * rate
        wage_limit = w2_wages * keep * wage_limit_rate
        component = full - max(full - wage_limit, 0.0) * frac
    income_limit = max(ti_before_qbi - net_capital_gain, 0) * rate
    deduction = whole(min(component, income_limit))
    if minimum_qbi and qbi * keep >= minimum_qbi:          # an SSTB past the range has no QBI left to count
        deduction = max(deduction, minimum_deduction)
    return deduction


def over_65_deduction(magi: int, people_65_or_over: int, amount: int, threshold: int, rate: float) -> int:
    """Schedule 1-A (2025) Part V, lines 31-37: $6,000 each, less 6% of MAGI over the threshold."""
    if people_65_or_over <= 0:
        return 0
    l33 = max(magi - threshold, 0)
    l34 = whole(l33 * rate)
    l35 = max(amount - l34, 0)
    return l35 * people_65_or_over


def state_and_local_tax_deduction(paid: int, magi: int, *, amount: int, threshold: int, rate: float, floor: int) -> int:
    """Schedule A (2025) line 5e worksheet: the cap, less 30% of MAGI over the threshold, never below $10,000."""
    cap = amount
    if magi > threshold:
        cap = max(amount - whole((magi - threshold) * rate), floor)
    return min(paid, cap)


def child_credit(children: int, other_dependents: int, agi: int, tax_before_credits: int, earned_income: int, *,
                 per_child: int, other_dependent: int, phase_out_start: int, phase_out_per_1000: int,
                 refundable_per_child: int, earned_income_floor: int, refundable_rate: float) -> tuple[int, int]:
    """Schedule 8812 (2025), Parts I and II-A: (the credit used against tax, the refundable additional credit).
    The alternative refundable calculation for three or more children (Part II-B) is not done."""
    credit = children * per_child + other_dependents * other_dependent
    if credit == 0:
        return 0, 0
    if agi > phase_out_start:
        credit = max(credit - math.ceil((agi - phase_out_start) / 1000) * phase_out_per_1000, 0)
    used = min(credit, max(tax_before_credits, 0))
    if children == 0:
        return used, 0
    # line 16a is the whole remaining credit, so the nonrefundable $500 is used up first; line 16b caps per child
    refundable = min(credit - used, children * refundable_per_child,
                     whole(max(earned_income - earned_income_floor, 0) * refundable_rate))
    return used, max(refundable, 0)
