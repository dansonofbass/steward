"""Where the next dollar goes (cash-flow and tax spec section 6). A made-up household: JR (44) and Sam (42), filing
jointly in California, $160,000 salary at 10% into the 401(k), a 50% match up to 6%, $72,000 a year of spending."""
import re
from dataclasses import replace

from steward.engine.decisions import business_plan_room, later_facts_estimate
from steward.engine.next_dollar import Debt, NextDollarInputs, next_dollar
from steward.engine.tax import annual_tax
from steward.engine.tax.facts import TaxFacts

BANNED = re.compile(r"\b(her|she|elder|senior|patient)\b", re.I)


def facts(**kw) -> TaxFacts:
    base = dict(filing="mfj", ages=(44, 42), state="CA", wages_cents=14_400_000, payroll_wages_cents=16_000_000,
                ss_wages_by_person_cents=(16_000_000, 0), dependents=(11,))
    base.update(kw)
    return TaxFacts(**base)


def inputs(**kw) -> NextDollarInputs:
    now = kw.pop("now", facts())
    base = dict(year=2026, month=10, owners=("JR", "Sam"), ages=(44, 42), spending_basis_cents=7_200_000,
                cash_cents=4_000_000, cash_months=3, has_business=False, business_profit_low_cents=0,
                salary_cents=16_000_000, k401_pct_bp=1_000, match_rate_bp=5_000, match_cap_bp=600,
                k401_in_cents=1_300_000, hsa_plan="yes", hsa_family=True, has_hsa_account=True, hsa_in_cents=120_000,
                ira_in_cents=(0, 0), business_plan_in_cents=None, debts=(), debt_rate_bp=700, taxable_in_cents=None,
                hsa_payroll_cents=0, k401_payroll_cents=0, now=now, later=later_facts_estimate(now, 7_200_000), real_return=0.05, inflation=0.025)
    base.update(kw)
    return NextDollarInputs(**base)


def step(i: NextDollarInputs, key: str):
    return next((s for s in next_dollar(i) if s.key == key), None)


def business(**kw) -> NextDollarInputs:
    """A sole proprietor with no W-2: $200,000 expected profit, $60,000 at the low end, a low bracket later."""
    base = dict(has_business=True, business_profit_low_cents=6_000_000, salary_cents=0, k401_pct_bp=0,
                match_rate_bp=0, match_cap_bp=0, k401_in_cents=None, cash_months=6, month=11,
                now=facts(wages_cents=0, payroll_wages_cents=0, ss_wages_by_person_cents=(0, 0),
                          business_profit_cents=20_000_000),
                later=TaxFacts(filing="mfj", ages=(67, 67), state="CA", ira_distributions_cents=4_000_000))
    base.update(kw)
    return inputs(**base)


def test_the_six_steps_come_in_the_specs_order():
    assert [s.key for s in next_dollar(inputs())] == ["cash", "match", "hsa", "debt", "retirement", "invest"]


def test_cash_against_three_or_six_months():
    s = step(inputs(), "cash")
    assert (s.title, s.status, s.in_cents, s.room_cents) == ("Cash for 3 months of spending", "done", 4_000_000, 0)
    assert s.why == "Cash accounts hold 6.6 months of spending; the target is 3."
    s = step(inputs(has_business=True, cash_months=6, cash_cents=2_000_000), "cash")
    assert (s.title, s.status, s.room_cents) == ("Cash for 6 months of spending", "to_do", 1_600_000)
    assert s.why == "Cash accounts hold 3.3 months of spending; the target is 6, because business income is uncertain."


def test_cash_without_spending_history_cant_tell():
    s = step(inputs(spending_basis_cents=0), "cash")
    assert s.status == "cant_tell" and s.why == "There is no spending history yet to set the target."


def test_the_match_is_met_or_says_what_raising_it_adds():
    s = step(inputs(), "match")
    assert (s.status, s.why, s.in_cents) == ("done", "Contributing 10% of pay meets the 6% match.", 1_300_000)
    s = step(inputs(k401_pct_bp=400), "match")
    assert (s.status, s.room_cents) == ("to_do", 320_000)
    assert s.why == "Contributing 4% of pay; raising it to 6% adds $1,600 a year from the employer."


def test_no_w2_match_leaves_the_step_out():
    assert step(inputs(match_rate_bp=0), "match") is None
    assert step(inputs(salary_cents=0), "match") is None


def test_hsa_asks_then_follows_the_answer():
    s = step(inputs(hsa_plan=None), "hsa")
    assert (s.status, s.why, s.room_cents) == ("ask", "Does your health plan qualify for an HSA?", None)
    s = step(inputs(hsa_plan="unsure"), "hsa")
    assert s.status == "ask" and s.why == "The plan's summary of benefits says whether it is HSA-qualified."
    assert step(inputs(hsa_plan="no"), "hsa") is None
    s = step(inputs(), "hsa")
    assert (s.status, s.in_cents, s.room_cents, s.rules_year) == ("to_do", 120_000, 755_000, 2026)
    assert s.why == "$1,200 in so far; the 2026 family limit is $8,750."
    s = step(inputs(has_hsa_account=False, hsa_in_cents=None, hsa_family=False, ages=(44,), owners=("JR",),
                    ira_in_cents=(0,), now=facts(filing="single", ages=(44,), ss_wages_by_person_cents=(16_000_000,))), "hsa")
    assert (s.status, s.room_cents) == ("to_do", 440_000) and s.why == "Open an HSA; the 2026 self-only limit is $4,400."
    s = step(inputs(hsa_in_cents=875_000), "hsa")
    assert (s.status, s.room_cents, s.why) == ("done", 0, "The 2026 family limit of $8,750 is in.")


def test_debt_above_the_rate_highest_first_and_asks_for_missing_rates():
    debts = (Debt(1, "Visa", 430_000, 2290, True), Debt(2, "Store card", 50_000, None, True),
             Debt(3, "Gas card", 20_000, None, False), Debt(4, "Mortgage", 40_000_000, 312, False, True),
             Debt(5, "Paid-off card", 0, 2500, False))
    s = step(inputs(debts=debts), "debt")
    assert (s.title, s.status, s.room_cents) == ("Debt above 7% interest", "to_do", 480_000)
    assert s.why == "Highest rate first: Visa (22.9%), Store card (rate not entered). $4,800 owed in all."
    assert s.needs_rate == ((2, "Store card"),)
    one = step(inputs(debts=debts[:1]), "debt")
    assert one.why == "Visa (22.9%): $4,300 owed."


def test_no_high_debt_is_done_and_the_threshold_is_a_setting():
    s = step(inputs(), "debt")
    assert (s.status, s.why) == ("done", "No debt above 7% interest.")
    s = step(inputs(debts=(Debt(1, "Car loan", 900_000, 650, False),), debt_rate_bp=600), "debt")
    assert s.title == "Debt above 6% interest" and s.room_cents == 900_000


def test_no_business_means_a_roth_ira_for_each_adult():
    s = step(inputs(), "retirement")
    assert (s.title, s.status, s.choice, s.room_cents, s.in_cents, s.rules_year) == \
        ("Roth IRA", "to_do", "roth_ira", 1_500_000, 0, 2026)
    assert s.why == "Room left: $7,500 for each of you (2026 limits)."
    s = step(inputs(ages=(51, 42), ira_in_cents=(100_000, 0)), "retirement")
    assert s.why == "Room left: $7,600 for JR and $7,500 for Sam (2026 limits)."
    s = step(inputs(ira_in_cents=(750_000, 750_000)), "retirement")
    assert (s.status, s.room_cents, s.why) == ("done", 0, "The 2026 limit is in.")


def test_a_single_filer_gets_one_roth_room():
    s = step(inputs(ages=(44,), owners=("JR",), ira_in_cents=(0,), hsa_family=False,
                    now=facts(filing="single", ages=(44,), ss_wages_by_person_cents=(16_000_000,))), "retirement")
    assert s.room_cents == 750_000 and s.why == "Room left: $7,500 (2026 limits)."


def test_over_the_income_limit_or_without_earned_income_there_is_no_roth_room():
    rich = facts(wages_cents=40_000_000, payroll_wages_cents=40_000_000, ss_wages_by_person_cents=(40_000_000, 0))
    s = step(inputs(now=rich, salary_cents=40_000_000), "retirement")
    assert (s.status, s.room_cents, s.why) == ("no_room", 0, "Your income is over the 2026 Roth IRA limit.")
    idle = facts(wages_cents=0, payroll_wages_cents=0, ss_wages_by_person_cents=(0, 0))
    s = step(inputs(now=idle, salary_cents=0, k401_pct_bp=0), "retirement")
    assert (s.status, s.why) == ("no_room", "A Roth IRA needs earned income this year.")


def test_the_business_plan_wins_when_this_years_bracket_is_higher():
    i = business()
    s = step(i, "retirement")
    se = annual_tax(replace(i.now, business_profit_cents=6_000_000), 2026, marginal=False).federal.se_tax_cents
    room = business_plan_room(6_000_000, se, 0, 44, 2026)[0]
    assert (s.title, s.status, s.choice, s.room_cents, s.rules_year) == ("Solo 401(k)", "to_do", "business_plan", room, 2026)
    assert re.fullmatch(r"A Solo 401\(k\) saves more this year: \d+% now against about \d+% later \(2026 rules\)\. "
                        r"Room at the low end of your profit range: \$[\d,]+ \(2026 limits\)\.", s.why), s.why


def test_before_october_the_business_plan_waits_for_profit_to_be_clearer():
    s = step(business(month=5), "retirement")
    assert s.status == "later" and s.choice == "business_plan"
    assert s.room_cents is None                   # no room figure until the year's profit is clearer (minor c)
    assert "Check back in October, once the year's profit is clearer." in s.why
    assert s.why.endswith("Meanwhile a Roth IRA has $15,000 of room.")


def test_a_business_with_no_profit_yet_gets_the_roth():
    s = step(business(business_profit_low_cents=0, now=facts(wages_cents=0, payroll_wages_cents=0,
                                                              ss_wages_by_person_cents=(0, 0))), "retirement")
    assert s.choice == "roth_ira"


def test_a_roth_lean_with_a_business_says_so_with_the_rates():
    i = business(business_profit_low_cents=2_000_000,
                 now=facts(wages_cents=0, payroll_wages_cents=0, ss_wages_by_person_cents=(0, 0),
                           business_profit_cents=3_000_000),
                 later=TaxFacts(filing="mfj", ages=(67, 67), state="CA", ira_distributions_cents=30_000_000))
    s = step(i, "retirement")
    assert s.choice == "roth_ira"
    assert re.match(r"A Roth IRA saves more this year: \d+% now against about \d+% later \(2026 rules\)\. Room left: ",
                    s.why), s.why


def test_mortgage_against_investing():
    pattern = r"about \d+\.\d% a year after tax \(2026 rules\)"
    s = step(inputs(), "invest")
    assert (s.title, s.choice, s.status, s.rules_year) == ("Taxable investing", "invest", "to_do", 2026)
    assert re.fullmatch(rf"No mortgage to pay down\. Investing is expected to earn {pattern}\.", s.why), s.why
    high = Debt(4, "Mortgage", 40_000_000, 680, False, True)
    s = step(inputs(debts=(high,)), "invest")
    assert (s.title, s.choice, s.room_cents) == ("Extra mortgage payments", "mortgage", 40_000_000)
    assert re.fullmatch(rf"The mortgage charges 6\.8%; investing is expected to earn {pattern}\.", s.why), s.why
    low = Debt(4, "Mortgage", 40_000_000, 287.5, False, True)
    s = step(inputs(debts=(low,)), "invest")
    assert s.choice == "invest"
    assert re.fullmatch(rf"Investing is expected to earn {pattern}, more than the mortgage's 2\.875%\.", s.why), s.why
    unknown = Debt(4, "Mortgage", 40_000_000, None, False, True)
    s = step(inputs(debts=(unknown,)), "invest")
    assert s.needs_rate == ((4, "Mortgage"),)
    assert s.why.endswith("Enter the mortgage rate to compare it with paying the mortgage down.")
    above = Debt(4, "Mortgage", 40_000_000, 750, False, True)
    s = step(inputs(debts=(above,)), "invest")
    assert s.choice == "invest" and s.why.endswith("The mortgage is paid down first, above.")
    assert step(inputs(debts=(above,)), "debt").room_cents == 40_000_000


def test_a_year_without_tables_says_which_years_rules():
    i = inputs(year=2027)
    whys = " ".join(s.why for s in next_dollar(i))
    assert "2027" not in whys and "2026 family limit" in whys and "(2026 limits)" in whys
    assert {s.rules_year for s in next_dollar(i) if s.rules_year is not None} == {2026}


def test_no_sentence_uses_words_the_spec_rules_out():
    cases = [inputs(), inputs(hsa_plan=None), business(), business(month=3), inputs(spending_basis_cents=0),
             inputs(debts=(Debt(1, "Visa", 430_000, None, True), Debt(4, "Mortgage", 40_000_000, 680, False, True)))]
    for i in cases:
        for s in next_dollar(i):
            assert not BANNED.search(s.why + s.title), s.why
            assert "!" not in s.why


def test_bad_inputs_are_refused_in_plain_words():
    import pytest
    from steward.engine.inputs import InputError
    with pytest.raises(InputError, match="one name, one age and one IRA total"):
        next_dollar(inputs(ira_in_cents=(0,)))
    with pytest.raises(InputError, match="from 1 to 24 months"):
        next_dollar(inputs(cash_months=0))
    with pytest.raises(InputError, match="between 0% and 100%"):
        next_dollar(inputs(debt_rate_bp=20_000))


def test_solo_401k_room_uses_the_business_owners_age_and_own_deferrals():
    """Sam (42) runs the business, JR (50) has the W-2 job: no catch-up for Sam, and JR's deferrals take nothing off."""
    kw = dict(ages=(50, 42), now=facts(ages=(50, 42), wages_cents=0, payroll_wages_cents=0,
                                       ss_wages_by_person_cents=(0, 0), business_profit_cents=20_000_000))
    i = business(business_owner=1, **kw)
    se = annual_tax(replace(i.now, business_profit_cents=6_000_000), 2026, marginal=False).federal.se_tax_cents
    s = step(i, "retirement")
    assert s.room_cents == business_plan_room(6_000_000, se, 0, 42, 2026)[0]
    assert s.room_cents < business_plan_room(6_000_000, se, 0, 50, 2026)[0]
    own = step(business(business_owner=1, business_owner_w2_deferral_cents=1_000_000, **kw), "retirement")
    assert own.room_cents == business_plan_room(6_000_000, se, 1_000_000, 42, 2026)[0]


def roth_lean(**kw) -> NextDollarInputs:
    """A thin business year and a high bracket later: the Roth IRA saves more."""
    base = dict(business_profit_low_cents=2_000_000,
                now=facts(wages_cents=0, payroll_wages_cents=0, ss_wages_by_person_cents=(0, 0),
                          business_profit_cents=3_000_000),
                later=TaxFacts(filing="mfj", ages=(67, 67), state="CA", ira_distributions_cents=30_000_000))
    base.update(kw)
    return business(**base)


def test_a_full_roth_ira_hands_the_next_dollar_to_the_solo_401k():
    """Final review I-1: the Roth leans ahead, but once it is full the Solo 401(k) is still better than taxable."""
    s = step(roth_lean(ira_in_cents=(750_000, 750_000)), "retirement")
    assert (s.title, s.status, s.choice) == ("Solo 401(k)", "to_do", "business_plan")
    assert s.room_cents > 0
    assert s.why.startswith("The Roth IRA limit is in, so a Solo 401(k) is next. Room at the low end of your profit "
                            "range: $"), s.why
    early = step(roth_lean(ira_in_cents=(750_000, 750_000), month=5), "retirement")
    assert (early.status, early.choice, early.room_cents) == ("later", "business_plan", None)
    assert early.why == ("The Roth IRA limit is in, so a Solo 401(k) is next. "
                         "Check back in October, once the year's profit is clearer.")


def test_a_full_solo_401k_hands_the_next_dollar_to_the_roth_ira():
    """The other lean: the Solo 401(k) saves more, and its room at the low end is in, so the Roth IRA is next."""
    s = step(business(business_plan_in_cents=5_000_000), "retirement")
    assert (s.title, s.status, s.choice, s.room_cents) == ("Roth IRA", "to_do", "roth_ira", 1_500_000)
    assert s.why == ("The Solo 401(k) room at the low end of your profit range is in, so a Roth IRA is next. "
                     "Room left: $7,500 for each of you (2026 limits).")


def test_both_full_is_done():
    s = step(roth_lean(ira_in_cents=(750_000, 750_000), business_plan_in_cents=5_000_000), "retirement")
    assert (s.status, s.room_cents) == ("done", 0)
    assert s.why == "The 2026 Roth IRA limit is in, and so is the Solo 401(k) room at the low end of your profit range."
    s = step(business(business_plan_in_cents=5_000_000, ira_in_cents=(750_000, 750_000)), "retirement")
    assert (s.status, s.choice, s.room_cents) == ("done", "business_plan", 0)
    assert s.why.endswith("The room at the low end of your profit range is in (2026 limits)."), s.why


def test_the_roth_earned_income_cap_uses_the_low_end_of_the_profit_range():
    """Minor b: the same low end as the plan room, not the middle of the range."""
    s = step(roth_lean(business_profit_low_cents=1_000_000), "retirement")
    assert (s.choice, s.room_cents) == ("roth_ira", 1_000_000)
    assert s.why.endswith("Room left: $10,000, up to this year's earned income (2026 limits).")


def test_payroll_money_counts_toward_the_hsa():
    """Final review I-3: what the paycheck puts in is entered, and counts with the tagged transfers."""
    s = step(inputs(hsa_payroll_cents=600_000), "hsa")
    assert (s.status, s.in_cents, s.room_cents, s.takes_payroll, s.payroll_cents) == \
        ("to_do", 720_000, 155_000, True, 600_000)
    assert s.why == "$7,200 in so far; the 2026 family limit is $8,750."
    s = step(inputs(hsa_payroll_cents=755_000), "hsa")
    assert (s.status, s.room_cents) == ("done", 0)


def test_a_blank_payroll_amount_hides_the_hsa_room_when_there_are_w2_wages():
    s = step(inputs(hsa_payroll_cents=None), "hsa")
    assert (s.status, s.in_cents, s.room_cents, s.takes_payroll, s.payroll_cents) == ("to_do", 120_000, None, True, None)
    unlinked = step(inputs(hsa_payroll_cents=None, has_hsa_account=False, hsa_in_cents=None), "hsa")
    assert unlinked.room_cents is None and unlinked.why.startswith("Open an HSA")   # it may be at work, not linked
    paid = step(inputs(hsa_payroll_cents=300_000, has_hsa_account=False, hsa_in_cents=None), "hsa")
    assert (paid.in_cents, paid.room_cents) == (300_000, 575_000)
    no_w2 = step(inputs(hsa_payroll_cents=None, salary_cents=0, k401_pct_bp=0), "hsa")
    assert (no_w2.room_cents, no_w2.takes_payroll) == (755_000, False)


def test_payroll_money_counts_toward_the_401k():
    s = step(inputs(k401_payroll_cents=1_000_000), "match")
    assert (s.in_cents, s.takes_payroll, s.payroll_cents) == (2_300_000, True, 1_000_000)
    s = step(inputs(k401_payroll_cents=None, k401_in_cents=None), "match")
    assert (s.in_cents, s.takes_payroll, s.payroll_cents) == (None, True, None)
