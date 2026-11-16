"""steward.engine.decisions (cash-flow and tax spec sections 6 and 7): the minimal versions part 4 builds and part 5
refines. Limits come from data/rules/retirement_2026.json."""
from dataclasses import replace

from steward.engine.decisions import (
    LATER_AGE, business_plan_room, expected_real_return, hsa_limit, k401_catch_up_cents, later_facts_estimate,
    retirement_choice, roth_ira_limit,
)
from steward.engine.inputs import Mix
from steward.engine.tax import annual_tax, rules
from steward.engine.tax.facts import TaxFacts

R = rules.table("retirement", 2026)


def high_earner() -> TaxFacts:
    return TaxFacts(filing="mfj", ages=(44, 42), state="CA", wages_cents=30_000_000,
                    ss_wages_by_person_cents=(30_000_000, 0))


def test_a_high_bracket_now_leans_pre_tax_and_a_low_one_leans_roth():
    later = TaxFacts(filing="mfj", ages=(67, 67), state="CA", ira_distributions_cents=6_000_000)
    c = retirement_choice(high_earner(), later, 2026)
    assert c.lean == "pretax" and c.now_rate > c.later_rate
    assert c.now_rate == annual_tax(high_earner(), 2026).marginal_rate
    assert c.later_rate == annual_tax(later, 2026).marginal_rate and c.rules_year == 2026
    low = TaxFacts(filing="mfj", ages=(30, 30), state="CA", wages_cents=4_000_000, ss_wages_by_person_cents=(4_000_000, 0))
    rich_later = TaxFacts(filing="mfj", ages=(67, 67), state="CA", ira_distributions_cents=25_000_000)
    assert retirement_choice(low, rich_later, 2026).lean == "roth"


def test_a_tie_leans_roth():
    same = high_earner()
    assert retirement_choice(same, same, 2026).lean == "roth"


def test_later_facts_estimate_treats_spending_as_withdrawals_from_67():
    later = later_facts_estimate(replace(high_earner(), ages=(44, 70)), 7_200_000)
    assert later.ages == (LATER_AGE, 70) and later.ira_distributions_cents == 7_200_000
    assert later.filing == "mfj" and later.state == "CA" and later.wages_cents == 0
    assert later_facts_estimate(high_earner(), -5).ira_distributions_cents == 0


def test_catch_up_by_age():
    assert k401_catch_up_cents(49, 2026) == 0
    assert k401_catch_up_cents(50, 2026) == R["k401_catch_up_50"] * 100 == 800_000
    assert [k401_catch_up_cents(a, 2026) for a in (60, 63)] == [1_125_000, 1_125_000]
    assert k401_catch_up_cents(64, 2026) == 800_000


def test_business_plan_room_is_deferral_plus_twenty_percent_of_net_earnings():
    # $100,000 profit, $14,130 SE tax: net earnings $92,935; employer $18,587; deferral $24,500
    assert business_plan_room(10_000_000, 1_413_000, 0, 44, 2026) == (4_308_700, 2026)
    # a W-2 401(k) already used $20,000 of the shared $24,500 deferral
    assert business_plan_room(10_000_000, 1_413_000, 2_000_000, 44, 2026) == (2_308_700, 2026)
    # 60 to 63 adds the larger catch-up on top
    assert business_plan_room(10_000_000, 1_413_000, 0, 61, 2026)[0] == 4_308_700 + 1_125_000


def test_business_plan_room_never_exceeds_net_earnings_or_the_overall_cap():
    assert business_plan_room(1_000_000, 141_300, 0, 44, 2026)[0] == 929_350        # all of net earnings
    assert business_plan_room(50_000_000, 0, 0, 44, 2026)[0] == R["overall_cap"] * 100 == 7_200_000
    assert business_plan_room(50_000_000, 0, 0, 61, 2026)[0] == 7_200_000 + 1_125_000
    assert business_plan_room(0, 0, 0, 44, 2026)[0] == 0
    assert business_plan_room(-500_000, 0, 0, 44, 2026)[0] == 0


def test_roth_ira_limit_phases_out_between_the_tables_bounds():
    for filing in ("mfj", "single"):
        lo, hi = (x * 100 for x in R["roth_ira_phaseout"][filing])
        full = R["ira"] * 100
        assert roth_ira_limit(lo, filing, 44, 2026) == (full, 2026)
        assert roth_ira_limit(hi, filing, 44, 2026) == (0, 2026)
        assert roth_ira_limit((lo + hi) // 2, filing, 44, 2026)[0] == full // 2
        assert roth_ira_limit(hi - 100, filing, 44, 2026)[0] == 20_000       # the $200 minimum
    assert roth_ira_limit(0, "mfj", 50, 2026)[0] == (R["ira"] + R["ira_catch_up_50"]) * 100 == 860_000


def test_roth_ira_limit_rounds_up_to_ten_dollars():
    lo, hi = (x * 100 for x in R["roth_ira_phaseout"]["mfj"])
    got = roth_ira_limit(lo + 123_456, "mfj", 44, 2026)[0]
    assert got % 1_000 == 0
    exact = 750_000 * (hi - lo - 123_456) / (hi - lo)
    assert exact <= got < exact + 1_000


def test_hsa_limit_family_self_and_catch_up():
    assert hsa_limit(True, (44, 42), 2026) == (875_000, 2026)
    assert hsa_limit(False, (44,), 2026) == (440_000, 2026)
    assert hsa_limit(True, (56, 42), 2026)[0] == 975_000
    assert hsa_limit(True, (56, 57), 2026)[0] == 1_075_000


def test_a_later_year_uses_the_latest_table():
    assert hsa_limit(True, (44, 42), 2027) == (875_000, 2026)
    assert roth_ira_limit(0, "mfj", 44, 2027) == (750_000, 2026)


def test_expected_real_return_is_the_mixs_long_run_growth():
    stock = expected_real_return(Mix(1.0, 0.0, 0.0))
    cash = expected_real_return(Mix(0.0, 0.0, 1.0))
    assert 0.03 < stock < 0.09 and cash < stock
    assert abs(expected_real_return(Mix(1.0, 0.0, 0.0, fee_bp=100)) - (stock - 0.01)) < 0.002


# Part 5 (tax decisions plan Task 3): the Publication 560 worksheet, the rate later, the line, converting.
import pytest

from steward.engine.decisions import (
    choice_line, conversion_room, self_employed_room,
)
from steward.engine.inputs import InputError
from steward.engine.tax.worksheets import schedule_se


def test_the_publication_560_example():
    # Pub. 560 (2025), Chapter 5: net profit $200,000, self-employment tax deduction $13,596, plan rate 8.5% (0.078).
    # Filled-in worksheet: step 3 $186,404, step 5 $14,540, maximum deduction $14,540.
    r = self_employed_room(200_000, 13_596, age=45, w2_deferrals=0, year=2026, plan_rate=0.085, employer_rate=0.078)
    assert r.net_earnings_cents == 18_640_400 and r.sep_cents == 1_454_000


def test_2026_at_100000_of_profit():
    # Schedule SE: 100,000 x 0.9235 = 92,350; x 15.3% = 14,129.55 -> 14,130; half 7,065. Step 3: 92,935.
    # SEP: 20% = 18,587. Solo 401(k): own 24,500 (step 9); step 12 = half of 68,435 = 34,218; business = 18,587;
    # step 15 = 24,500; total 43,087 (part 4's business_plan_room agrees).
    r = self_employed_room(100_000, 7_065, age=44, w2_deferrals=0, year=2026)
    assert (r.net_earnings_cents, r.sep_cents) == (9_293_500, 1_858_700)
    assert (r.solo_own_cents, r.solo_business_cents, r.solo_catch_up_cents, r.solo_total_cents) == (2_450_000, 1_858_700, 0, 4_308_700)
    assert (r.deferral_limit_cents, r.used_elsewhere_cents, r.rules_year) == (2_450_000, 0, 2026)


def test_w2_deferrals_use_the_same_24500():
    # A $165,000 salary deferring 8% ($13,200) leaves $11,300 of own part. Schedule SE with $165,000 of wages:
    # 92,350 x 2.9% = 2,678.15, plus 12.4% of the 19,500 left under the wage base = 2,418; 5,096; half 2,548.
    r = self_employed_room(100_000, 2_548, age=44, w2_deferrals=13_200, year=2026)
    assert r.net_earnings_cents == 9_745_200 and r.sep_cents == 1_949_000
    assert (r.solo_own_cents, r.solo_business_cents, r.solo_total_cents) == (1_130_000, 1_949_000, 3_079_000)
    assert r.used_elsewhere_cents == 1_320_000
    full = self_employed_room(100_000, 2_548, age=44, w2_deferrals=24_500, year=2026)
    assert full.solo_own_cents == 0 and full.solo_total_cents == full.sep_cents


def test_catch_up_at_61():
    # 50,000 x 0.9235 = 46,175; x 15.3% = 7,064.78 -> 7,065; half 3,532.5 -> 3,533. Step 3: 46,467. SEP 9,293.
    # Solo: own 24,500; business min(9,293, 47,500, 10,984) = 9,293; step 14 = 37,174; step 16 = 12,674; catch-up 11,250.
    r = self_employed_room(50_000, 3_533, age=61, w2_deferrals=0, year=2026)
    assert (r.sep_cents, r.solo_own_cents, r.solo_business_cents, r.solo_catch_up_cents, r.solo_total_cents) == (
        929_300, 2_450_000, 929_300, 1_125_000, 4_504_300)


def test_a_small_profit_goes_to_the_own_part_first():
    # 20,000: SE 2,826, half 1,413; step 3 18,587. The own part takes all of it; step 12 is 0, so no business part.
    r = self_employed_room(20_000, 1_413, age=44, w2_deferrals=0, year=2026)
    assert (r.sep_cents, r.solo_own_cents, r.solo_business_cents, r.solo_total_cents) == (371_700, 1_858_700, 0, 1_858_700)


def test_no_profit_no_room():
    r = self_employed_room(-5_000, 0, age=44, w2_deferrals=0, year=2026)
    assert (r.net_earnings_cents, r.sep_cents, r.solo_total_cents) == (0, 0, 0)


@pytest.mark.parametrize("profit", [5_000, 20_000, 50_000, 100_000, 180_000, 400_000])
@pytest.mark.parametrize("age, w2", [(44, 0), (44, 13_200), (61, 0)])
def test_the_worksheet_and_part_4s_room_agree(profit, age, w2):
    # Within a dollar, except where step 12 trims the business part because the own part is large against a small
    # profit ($20,000 with $13,200 already deferred: the worksheet's $14,944 against part 4's $15,017.40). The
    # worksheet is never higher.
    se_tax, se_half, _ = schedule_se(profit, 0, 184_500, 0.9235, 0.124, 0.029, 400)
    room = self_employed_room(profit, se_half, age=age, w2_deferrals=w2, year=2026)
    theirs, _ = business_plan_room(profit * 100, se_tax * 100, w2 * 100, age, 2026)
    assert room.solo_total_cents <= theirs + 100
    if profit >= 50_000 or w2 == 0:
        assert abs(room.solo_total_cents - theirs) <= 100


def test_the_line_says_the_lean_with_the_numbers():
    assert choice_line(0.12, 0.22) == "Roth this year: 12% now against about 22% later."
    assert choice_line(0.31, 0.22) == "Traditional this year: 31% now against about 22% later."
    assert choice_line(0.22, 0.23) == "About the same: 22% now against about 23% later. Either works."


def test_a_rate_later_from_the_projection_replaces_the_later_facts():
    now = high_earner()
    c = retirement_choice(now, None, 2026, rate_later=0.45)
    assert c.lean == "roth" and c.later_rate == 0.45 and c.now_rate == annual_tax(now, 2026).marginal_rate
    assert c.about_same is False and c.line == choice_line(c.now_rate, 0.45)
    close = retirement_choice(now, None, 2026, rate_later=c.now_rate + 0.01)
    assert close.about_same is True and close.lean == "roth"           # part 4's tie rule still leans Roth
    with pytest.raises(InputError):
        retirement_choice(now, None, 2026)


def test_part_4s_positional_calls_behave_as_before():
    later = TaxFacts(filing="mfj", ages=(67, 67), state="CA", ira_distributions_cents=6_000_000)
    c = retirement_choice(high_earner(), later, 2026)
    assert c.lean == "pretax" and c.later_rate == annual_tax(later, 2026).marginal_rate
    assert c.line == choice_line(c.now_rate, c.later_rate)


def test_a_low_income_year_is_flagged_for_converting():
    # $40,000 of wages: taxable $7,800, so the 10% bracket has $17,000 left before $24,800
    f = TaxFacts(filing="mfj", ages=(44, 42), state="CA", wages_cents=4_000_000)
    result = annual_tax(f, 2026)
    conv = conversion_room(f, 2026, result, traditional_cents=45_000_000, rate_later=0.22)
    assert conv is not None and conv.amount_cents == 1_700_000 and conv.bracket_rate == 0.10
    assert 190_000 <= conv.tax_cents <= 220_000                    # $1,700 federal and about 2% California
    assert conv.line.startswith("This year's rate is low: converting $17,000 of traditional money to Roth would cost about $")
    assert conv.line.endswith("in tax, filling the 10% federal bracket (2026 rules).")
    assert conversion_room(f, 2026, result, traditional_cents=45_000_000, rate_later=0.12) is None
    assert conversion_room(f, 2026, result, traditional_cents=0, rate_later=0.22) is None
    assert conversion_room(f, 2026, result, traditional_cents=45_000_000, rate_later=None) is None
    small = conversion_room(f, 2026, result, traditional_cents=500_000, rate_later=0.22)
    assert small is not None and small.amount_cents == 500_000


def test_now_and_later_use_the_same_rules_year():
    # carried item 3: the later facts are taxed under the same year's rules as this year's (pinned to one year)
    later = TaxFacts(filing="mfj", ages=(67, 67), state="CA", ira_distributions_cents=6_000_000)
    c = retirement_choice(high_earner(), later, 2026)
    assert c.rules_year == annual_tax(later, 2026).rules_year == annual_tax(high_earner(), 2026).rules_year
    assert retirement_choice(high_earner(), None, 2026, rate_later=0.22).rules_year == c.rules_year
