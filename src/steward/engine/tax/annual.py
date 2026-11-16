"""The exact one-year calculator (spec 3.1, 3.3): annual_tax(facts, year) -> TaxResult.

It follows Form 1040 and its schedules in whole dollars: Schedule SE, Publication 915's Social Security worksheet,
Schedule 1-A's deduction for people 65 and over, Schedule A (medical floor, the state and local tax cap, the 2026
charitable floor and the limit on itemized deductions in the top bracket), Form 8995 / 8995-A for one business with
no business property, the Tax Table and the Qualified Dividends and Capital Gain Tax Worksheet, Form 8959, Form 8960
and Schedule 8812. Then the state module for facts.state.

Not calculated (named in NOT_CALCULATED): the alternative minimum tax, the kiddie tax, the tips, overtime and car-loan
interest deductions, the earned income credit, education and child-care credits, the premium tax credit, and the
three-or-more-children refundable credit calculation.
"""
from __future__ import annotations

from dataclasses import replace

from steward.engine.tax import rules
from steward.engine.tax import worksheets as w
from steward.engine.tax.facts import FederalFigures, FederalTax, TaxFacts, TaxResult, validate_facts
from steward.engine.tax.state import state_tax

NOT_CALCULATED = (
    "the alternative minimum tax", "the kiddie tax", "the tips, overtime and car-loan interest deductions",
    "the earned income credit", "education and child-care credits", "the premium tax credit",
    "the three-or-more-children refundable credit calculation",
)
MARGINAL_STEP_CENTS = 10_000   # the next $100 of ordinary income


def _money(dollars: int) -> str:
    return f"${dollars:,}" if dollars >= 0 else f"-${-dollars:,}"


def _compute(f: TaxFacts, year: int) -> TaxResult:
    F = rules.table("federal", year)
    P = rules.table("payroll", year)
    filing = f.filing
    d = lambda cents: w.whole(cents / 100)  # noqa: E731
    wages, profit, scorp = d(f.wages_cents), d(f.business_profit_cents), d(f.scorp_profit_cents)
    payroll_wages = wages if f.payroll_wages_cents is None else d(f.payroll_wages_cents)
    interest, exempt_interest = d(f.interest_cents), d(f.tax_exempt_interest_cents)
    dividends, qualified = d(f.ordinary_dividends_cents), d(f.qualified_dividends_cents)
    st, lt = d(f.short_term_gains_cents), d(f.long_term_gains_cents)
    ira, pensions, ss, other = d(f.ira_distributions_cents), d(f.pensions_cents), d(f.social_security_cents), d(f.other_income_cents)
    se_ret, se_health, hsa, ira_ded = d(f.se_retirement_cents), d(f.se_health_insurance_cents), d(f.hsa_contributions_cents), d(f.ira_deduction_cents)
    explain: list[str] = []
    if F.year < year:
        explain.append(f"Using {F.year} federal rules (the latest published).")

    # Schedule SE is the owner's own: line 8a counts only their Social Security wages against the wage base
    if f.ss_wages_by_person_cents:
        owner_wages = d(f.ss_wages_by_person_cents[f.business_owner])
    else:
        owner_wages = payroll_wages if filing == "single" else 0
    se = P["se"]
    se_tax, se_half, se_net = w.schedule_se(profit, owner_wages, P["wage_base"], se["net_factor"], se["oasdi_rate"],
                                            se["medicare_rate"], se["minimum_net_earnings"])
    # Schedule D: net gain, or a loss up to $3,000; the preferential part is the smaller of long-term and total
    net_gain = st + lt
    capital_line = net_gain if net_gain >= 0 else max(net_gain, -F["capital_loss_limit"])
    net_capital_gain = max(min(lt, net_gain), 0)

    income_before_ss = wages + profit + scorp + interest + dividends + capital_line + ira + pensions + other
    adjustments = se_half + se_ret + se_health + hsa + ira_ded
    taxable_ss = w.taxable_social_security(ss, income_before_ss, exempt_interest, adjustments, F["ss_thresholds"][filing])
    agi = income_before_ss + taxable_ss - adjustments

    # Deductions
    n65 = sum(1 for a in f.ages if a >= 65)
    standard = F["standard_deduction"][filing] + n65 * F["aged_additional"][filing]
    medical = max(d(f.medical_cents) - w.whole(agi * F["medical_floor"]), 0)
    sc = F["salt_cap"]
    salt = w.state_and_local_tax_deduction(d(f.state_income_tax_cents) + d(f.property_tax_cents), agi,
                                           amount=sc["amount"], threshold=sc["threshold"], rate=sc["rate"], floor=sc["floor"])
    charity = d(f.charity_cents)
    ch = F["charity"]
    charity_itemized = max(charity - w.whole(agi * ch["itemized_floor"]), 0) if ch else charity
    itemized_total = medical + salt + d(f.mortgage_interest_cents) + charity_itemized
    o65 = F["over_65_deduction"]
    over65 = w.over_65_deduction(agi, n65, o65["amount"], o65["threshold"][filing], o65["rate"]) if year <= o65["last_year"] else 0
    # A non-itemizer also gets the 2026 charity deduction, so itemizing has to beat the standard deduction plus that
    non_itemizer_charity = min(charity, ch["non_itemizer_cap"][filing]) if ch else 0
    itemized = itemized_total > standard + non_itemizer_charity
    deduction = itemized_total if itemized else standard
    charity_standard = min(charity, ch["non_itemizer_cap"][filing]) if (ch and not itemized) else 0
    ti_before_qbi = max(agi - deduction - over65 - charity_standard, 0)

    # QBI (Form 8995 / 8995-A), from taxable income before the itemized limit
    q = F["qbi"]
    qbi = profit - se_half - se_health - se_ret + scorp
    qbi_ded = w.qbi_deduction(qbi, d(f.business_w2_wages_cents), f.business_sstb, ti_before_qbi, net_capital_gain + qualified,
                              rate=q["rate"], threshold=q["threshold"][filing], phase_in=q["phase_in"][filing],
                              wage_limit_rate=q["wage_limit_rate"], minimum_deduction=q["minimum_deduction"],
                              minimum_qbi=q["minimum_qbi"])
    # The 2026 limit on itemized deductions for the top bracket (section 68)
    lim = F["itemized_limit"]
    if itemized and lim:
        top = F["brackets"][filing][-1][0]
        # Section 68(a)(2): taxable income with the itemized deductions added back, above the top bracket's floor
        over = ti_before_qbi - qbi_ded + itemized_total - top
        if over > 0:
            cut = w.whole(min(itemized_total, over) * lim["numerator"] / lim["denominator"])
            deduction -= cut
            explain.append(f"The limit on itemized deductions in the top bracket took back {_money(cut)}.")
            ti_before_qbi += cut
    ti = max(ti_before_qbi - qbi_ded, 0)

    # Income tax
    brackets = F["brackets"][filing]
    if qualified + net_capital_gain > 0:
        ordinary_tax, gains_tax = w.qualified_dividends_and_capital_gain_tax(brackets, F["ltcg"][filing], ti, qualified,
                                                                            net_capital_gain)
    else:
        ordinary_tax, gains_tax = w.federal_income_tax(brackets, ti), 0
    income_tax = ordinary_tax + gains_tax

    # Surtaxes
    am = F["additional_medicare"]
    addl_medicare = w.additional_medicare_tax(payroll_wages, se_net if se_tax else 0.0, am["threshold"][filing], am["rate"])
    ni = F["niit"]
    nii = interest + dividends + max(net_gain, 0)
    niit = w.whole(min(nii, max(agi - ni["threshold"][filing], 0)) * ni["rate"])

    # Credits (Schedule 8812)
    cc = F["child_credit"]
    children = sum(1 for a in f.dependents if a < cc["child_under_age"])
    others = len(f.dependents) - children
    earned = wages + max(profit - se_half, 0)
    credit_used, refundable = w.child_credit(children, others, agi, income_tax, earned, per_child=cc["per_child"],
                                             other_dependent=cc["other_dependent"],
                                             phase_out_start=cc["phase_out_start"][filing],
                                             phase_out_per_1000=cc["phase_out_per_1000"],
                                             refundable_per_child=cc["refundable_per_child"],
                                             earned_income_floor=cc["earned_income_floor"],
                                             refundable_rate=cc["refundable_rate"])
    federal_total = income_tax - credit_used + se_tax + addl_medicare + niit - refundable

    state = state_tax(f, year, FederalFigures(agi=agi, taxable_social_security=taxable_ss, hsa_deduction=hsa))
    total = federal_total + state.tax_cents // 100
    gross = wages + max(profit, 0) + max(scorp, 0) + interest + exempt_interest + dividends + max(net_gain, 0) + ira + pensions + ss + other

    # Plain lines for the UI and chat
    if agi <= 0:
        pass                                      # with no income, no deduction lowered anything
    elif itemized:
        explain.append(f"Itemized deductions of {_money(itemized_total)} were more than the {_money(standard)} standard deduction.")
        if medical:
            explain.append(f"The medical deduction lowered taxable income by {_money(medical)}.")
    else:
        explain.append(f"The standard deduction of {_money(standard)} lowered taxable income.")
    if charity_standard:
        explain.append(f"Gifts to charity lowered taxable income by {_money(charity_standard)} without itemizing.")
    if over65 and agi > deduction:
        explain.append(f"The deduction for people 65 and over lowered taxable income by {_money(over65)}.")
    if taxable_ss:
        explain.append(f"{_money(taxable_ss)} of {_money(ss)} in Social Security is taxable.")
    elif ss:
        explain.append("None of the Social Security is taxable.")
    if se_tax:
        explain.append(f"Self-employment tax is {_money(se_tax)}; half of it, {_money(se_half)}, comes off income.")
    if qbi_ded:
        explain.append(f"The business income deduction lowered taxable income by {_money(qbi_ded)}.")
    if credit_used + refundable:
        explain.append(f"The child and dependent credits are {_money(credit_used + refundable)}.")
    if niit:
        explain.append(f"The 3.8% tax on investment income is {_money(niit)}.")
    if addl_medicare:
        explain.append(f"The additional 0.9% Medicare tax is {_money(addl_medicare)}.")
    explain.extend(state.explain)

    c = lambda dollars: dollars * 100  # noqa: E731
    return TaxResult(
        year=year, rules_year=F.year, agi_cents=c(agi), taxable_income_cents=c(ti), deduction_cents=c(deduction),
        itemized=itemized, over_65_deduction_cents=c(over65), qbi_deduction_cents=c(qbi_ded),
        taxable_social_security_cents=c(taxable_ss),
        federal=FederalTax(ordinary_cents=c(ordinary_tax), capital_gains_cents=c(gains_tax), se_tax_cents=c(se_tax),
                           additional_medicare_cents=c(addl_medicare), niit_cents=c(niit)),
        credits_cents=c(credit_used + refundable), federal_total_cents=c(federal_total), state=state,
        total_tax_cents=c(total), withholding_cents=f.federal_withholding_cents + f.state_withholding_cents,
        marginal_rate=0.0, effective_rate=round(total / gross, 4) if gross > 0 else 0.0, explain=tuple(explain),
    )


def annual_tax(facts: TaxFacts, year: int, *, marginal: bool = True) -> TaxResult:
    """The federal and state tax for one year under the rules in force that year (spec 3.1).
    marginal=False skips the second pass that finds the marginal rate (left at 0.0); project() uses it."""
    validate_facts(facts)
    base = _compute(facts, year)
    if not marginal:
        return base
    bumped = _compute(replace(facts, ira_distributions_cents=facts.ira_distributions_cents + MARGINAL_STEP_CENTS), year)
    rate = (bumped.total_tax_cents - base.total_tax_cents) / MARGINAL_STEP_CENTS
    return replace(base, marginal_rate=round(rate, 4))
