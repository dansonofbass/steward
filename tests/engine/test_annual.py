"""annual_tax (spec 3.1, 3.3, 9): whole returns worked line by line from the 2025/2026 forms, to the dollar.

The IRS no longer publishes filled-in sample returns, so each case below states its inputs and walks the form lines
in comments; every line rests on a worksheet that tests/engine/test_worksheets.py pins against a published example.
Fictional people only: Margaret Ellis (the demo parent) and the demo household."""
import pytest

from steward.engine.inputs import InputError
from steward.engine.tax import TaxFacts, annual_tax
from steward.engine.tax.rules import RulesError

MARGARET = TaxFacts(filing="single", ages=(82,), state="CA", social_security_cents=2_800_000, ira_distributions_cents=3_000_000,
                    pensions_cents=1_200_000, interest_cents=150_000, medical_cents=4_500_000, property_tax_cents=420_000,
                    charity_cents=100_000)
HOUSEHOLD = TaxFacts(filing="mfj", ages=(44, 42), state="CA", business_profit_cents=9_000_000, business_sstb=True,
                     interest_cents=40_000, ordinary_dividends_cents=120_000, qualified_dividends_cents=100_000,
                     hsa_contributions_cents=500_000, se_health_insurance_cents=1_200_000, mortgage_interest_cents=1_400_000,
                     property_tax_cents=900_000, state_income_tax_cents=300_000, charity_cents=200_000, dependents=(11, 8, 5))


def test_margaret_in_assisted_living_2026():
    r = annual_tax(MARGARET, 2026)
    # Pub 915 Worksheet 1: other income 43,500 (IRA 30,000 + pension 12,000 + interest 1,500); 85% cap -> 23,800
    assert r.taxable_social_security_cents == 2_380_000
    assert r.agi_cents == 6_730_000                                   # 43,500 + 23,800
    # Schedule A: medical 45,000 - 7.5% x 67,300 (5,048) = 39,952; taxes 4,200; charity 1,000 - 0.5% x 67,300 (337) = 663
    assert r.itemized and r.deduction_cents == 4_481_500               # 44,815 > 16,100 + 2,050
    assert r.over_65_deduction_cents == 600_000                        # Schedule 1-A: MAGI under $75,000
    assert r.taxable_income_cents == 1_648_500                         # 67,300 - 44,815 - 6,000
    assert r.federal.ordinary_cents == 172_900                         # Tax Table row 16,450-16,500: 1,240 + 12% x 4,075
    # California: AGI 43,500 (no Social Security); itemized 39,952 + 4,200 + 1,000 = 45,152 -> taxable income 0
    assert r.state.calculated and r.state.agi_cents == 4_350_000 and r.state.taxable_income_cents == 0 and r.state.tax_cents == 0
    assert r.state.rules_year == 2025 and r.rules_year == 2026
    assert r.total_tax_cents == 172_900 and r.effective_rate == pytest.approx(1_729 / 71_500, abs=1e-4)
    assert "The medical deduction lowered taxable income by $39,952." in r.explain
    assert "The deduction for people 65 and over lowered taxable income by $6,000." in r.explain
    assert "Using 2025 California rules (the latest published)." in r.explain


def test_the_demo_household_with_a_sole_proprietorship_2026():
    r = annual_tax(HOUSEHOLD, 2026)
    # Schedule SE: 90,000 x 0.9235 = 83,115; x 15.3% = 12,717; half 6,359
    assert r.federal.se_tax_cents == 1_271_700
    # AGI: 90,000 + 400 + 1,200 - (6,359 + 12,000 health insurance + 5,000 HSA) = 68,241
    assert r.agi_cents == 6_824_100
    # itemized 12,000 + 14,000 + (2,000 - 341) = 27,659 < 32,200, so the standard deduction and $2,000 of charity
    assert not r.itemized and r.deduction_cents == 3_220_000
    # QBI 90,000 - 6,359 - 12,000 = 71,641; limited to 20% x (34,041 - 1,000 qualified dividends) = 6,608
    assert r.qbi_deduction_cents == 660_800 and r.taxable_income_cents == 2_743_300
    # QDCG worksheet: line 5 26,433 -> Tax Table 2,675; the 1,000 of dividends at 0%; line 24 2,795 is larger
    assert (r.federal.ordinary_cents, r.federal.capital_gains_cents) == (267_500, 0)
    # Schedule 8812: 3 x 2,200; 2,675 used against tax; refundable min(3,925, 5,100, 15% x 81,141) = 3,925
    assert r.credits_cents == 660_000
    assert r.federal_total_cents == 879_200                            # 2,675 - 2,675 + 12,717 - 3,925
    # California: AGI 73,241 (the HSA deduction added back); itemized 25,000; Tax Table at 48,200 = 742;
    # credits 2 x 153 + 3 x 475 = 1,731, capped at the tax
    assert r.state.agi_cents == 7_324_100 and r.state.taxable_income_cents == 4_824_100
    assert r.state.credits_cents == 74_200 and r.state.tax_cents == 0
    assert r.total_tax_cents == 879_200
    assert "Self-employment tax is $12,717; half of it, $6,359, comes off income." in r.explain
    assert "Gifts to charity lowered taxable income by $2,000 without itemizing." in r.explain


def test_a_high_earner_hits_every_limit_2026():
    f = TaxFacts(filing="single", ages=(50,), state="CA", wages_cents=80_000_000, interest_cents=2_000_000,
                 ordinary_dividends_cents=3_000_000, qualified_dividends_cents=3_000_000, long_term_gains_cents=10_000_000,
                 state_income_tax_cents=7_000_000, property_tax_cents=1_500_000, mortgage_interest_cents=2_000_000,
                 charity_cents=5_000_000, federal_withholding_cents=20_000_000)
    r = annual_tax(f, 2026)
    assert r.agi_cents == 95_000_000
    # SALT: 85,000 paid, the cap falls to the $10,000 floor (MAGI 950,000 is 445,000 over $505,000);
    # itemized 10,000 + 20,000 + (50,000 - 4,750) = 75,250; the top-bracket limit takes 2/37 x 75,250 = 4,068 back
    assert r.itemized and r.deduction_cents == 7_118_200 and r.taxable_income_cents == 87_881_800
    # QDCG: line 5 748,818 -> 233,020; 130,000 at 20% = 26,000 (above the 15% band's 545,500 ceiling)
    assert (r.federal.ordinary_cents, r.federal.capital_gains_cents) == (23_302_000, 2_600_000)
    assert r.federal.additional_medicare_cents == 540_000              # 0.9% x 600,000
    assert r.federal.niit_cents == 570_000                             # 3.8% x 150,000 of investment income
    # California: itemized 85,000 less min(80% x 85,000, 6% x 697,797) = 43,132; tax on 906,868 = 92,381; credits phased out
    assert r.state.taxable_income_cents == 90_686_800 and r.state.tax_cents == 9_238_100 and r.state.credits_cents == 0
    assert r.total_tax_cents == 36_250_100 and r.withholding_cents == 20_000_000
    assert r.marginal_rate == pytest.approx(0.50, abs=0.02)


def test_retired_couple_with_the_deduction_for_people_65_and_over_2026():
    f = TaxFacts(filing="mfj", ages=(68, 66), state="CA", social_security_cents=4_600_000, pensions_cents=3_000_000,
                 ira_distributions_cents=2_000_000, interest_cents=300_000)
    r = annual_tax(f, 2026)
    # Pub 915: other income 53,000; line 8 76,000; line 17 6,000 + 27,200 = 33,200 (under 85% x 46,000)
    assert r.taxable_social_security_cents == 3_320_000 and r.agi_cents == 8_620_000
    assert r.deduction_cents == 3_550_000 and r.over_65_deduction_cents == 1_200_000   # 32,200 + 2 x 1,650; 2 x 6,000
    assert r.taxable_income_cents == 3_870_000 and r.federal.ordinary_cents == 415_100  # row 38,700-38,750
    # California: AGI 53,000, taxable 41,588, Tax Table 610; credits 4 x 153 = 612, capped at 610
    assert r.state.taxable_income_cents == 4_158_800 and r.state.tax_cents == 0
    assert r.total_tax_cents == 415_100


def test_after_2028_the_deduction_for_people_65_and_over_is_gone_and_2026_rules_carry_on():
    r = annual_tax(MARGARET, 2029)
    assert r.over_65_deduction_cents == 0 and r.rules_year == 2026
    assert "Using 2026 federal rules (the latest published)." in r.explain


def test_a_state_without_a_module_is_named_not_guessed():
    from dataclasses import replace
    r = annual_tax(replace(MARGARET, state="NY"), 2026)
    assert not r.state.calculated and r.state.tax_cents == 0
    assert "State tax isn't calculated for New York yet." in r.explain
    tx = annual_tax(replace(MARGARET, state="TX"), 2026)
    assert tx.state.calculated and tx.state.tax_cents == 0 and "Texas has no income tax on wages." in tx.explain
    wa = annual_tax(replace(MARGARET, state="WA"), 2026)
    assert "Washington's tax on large capital gains isn't calculated." in wa.explain


def test_bad_facts_are_refused_in_plain_words():
    from dataclasses import replace
    with pytest.raises(InputError, match="one age for a single return"):
        annual_tax(replace(MARGARET, ages=(82, 80)), 2026)
    with pytest.raises(InputError, match="can't be negative"):
        annual_tax(replace(MARGARET, medical_cents=-1), 2026)
    with pytest.raises(InputError, match="whole number of cents"):
        annual_tax(replace(MARGARET, interest_cents=12.5), 2026)
    with pytest.raises(InputError, match="two-letter code"):
        annual_tax(replace(MARGARET, state="California"), 2026)
    with pytest.raises(InputError, match="can't be larger"):
        annual_tax(replace(MARGARET, qualified_dividends_cents=1), 2026)
    with pytest.raises(RulesError, match="no federal rules for 2019"):
        annual_tax(MARGARET, 2019)


def test_a_business_loss_and_a_capital_loss_lower_income_as_the_forms_allow():
    f = TaxFacts(filing="single", ages=(40,), state="TX", wages_cents=6_000_000, business_profit_cents=-500_000,
                 short_term_gains_cents=-900_000)
    r = annual_tax(f, 2026)
    assert r.agi_cents == (60_000 - 5_000 - 3_000) * 100              # the capital loss is limited to $3,000
    assert r.federal.se_tax_cents == 0 and r.qbi_deduction_cents == 0
    assert r.effective_rate == pytest.approx(r.total_tax_cents / 6_000_000, abs=1e-4)


def test_a_year_with_no_income_owes_nothing_and_divides_by_nothing():
    # Review Focus 3: a parent whose only money this year is savings spent down: no tax, rates of zero, no error
    r = annual_tax(TaxFacts(filing="single", ages=(90,), state="CA"), 2026)
    assert r.total_tax_cents == 0 and r.effective_rate == 0.0 and r.marginal_rate == 0.0
    assert r.explain == ("Using 2025 California rules (the latest published).",)


def test_itemizing_has_to_beat_the_standard_deduction_plus_the_charity_a_non_itemizer_gets_2026():
    base = TaxFacts(filing="single", ages=(40,), state="TX", wages_cents=10_000_000, charity_cents=100_000)
    plain = annual_tax(base, 2026)
    assert not plain.itemized and plain.deduction_cents == 1_610_000 and plain.taxable_income_cents == 8_290_000
    from dataclasses import replace
    # itemized 16,200 + (1,000 - 0.5% x 100,000) = 16,700 is more than 16,100 but less than 16,100 + 1,000
    r = annual_tax(replace(base, mortgage_interest_cents=1_620_000), 2026)
    assert not r.itemized and r.deduction_cents == 1_610_000 and r.taxable_income_cents == plain.taxable_income_cents
    assert r.total_tax_cents == plain.total_tax_cents
    # a little more mortgage interest does tip it
    r2 = annual_tax(replace(base, mortgage_interest_cents=1_700_000), 2026)
    assert r2.itemized and r2.total_tax_cents < plain.total_tax_cents


def test_the_top_bracket_limit_counts_the_itemized_deductions_added_back_2026():
    # Section 68(a)(2): taxable income 600,000 + itemized 75,000 = 675,000, which is 34,400 over the 640,600 floor
    f = TaxFacts(filing="single", ages=(40,), state="TX", wages_cents=67_500_000, mortgage_interest_cents=7_500_000)
    r = annual_tax(f, 2026)
    assert r.itemized
    assert r.deduction_cents == 7_500_000 - 185_900                    # 2/37 x 34,400 = 1,859 taken back
    assert r.taxable_income_cents == 60_000_000 + 185_900
    assert "The limit on itemized deductions in the top bracket took back $1,859." in r.explain


def test_self_employment_tax_uses_only_the_business_owners_own_wages_on_a_joint_return_2026():
    # Final review I1: Schedule SE is per person; line 8a is the owner's own Social Security wages, not the return's.
    # The spouse earns $150,000 in wages; the owner has a $150,000 Schedule C profit and no wages of their own.
    alone = annual_tax(TaxFacts(filing="mfj", ages=(44, 42), state="CA", business_profit_cents=15_000_000), 2026)
    both = annual_tax(TaxFacts(filing="mfj", ages=(44, 42), state="CA", business_profit_cents=15_000_000,
                               wages_cents=15_000_000, ss_wages_by_person_cents=(0, 15_000_000), business_owner=0), 2026)
    assert alone.federal.se_tax_cents == 2_119_400                     # 150,000 x 92.35% x 15.3%
    assert both.federal.se_tax_cents == alone.federal.se_tax_cents
    # The owner's own wages do still use up the wage base
    own = annual_tax(TaxFacts(filing="mfj", ages=(44, 42), state="CA", business_profit_cents=15_000_000,
                              wages_cents=15_000_000, ss_wages_by_person_cents=(15_000_000, 0), business_owner=0), 2026)
    assert own.federal.se_tax_cents < alone.federal.se_tax_cents


def test_a_joint_return_with_no_wages_by_person_counts_none_of_the_wages_against_the_owners_wage_base_2026():
    # Without each person's wages, the household's wages can't be assumed to be the owner's: the full SE tax (the
    # side that sets more aside). A single return's wages are the owner's own.
    joint = annual_tax(TaxFacts(filing="mfj", ages=(44, 42), state="CA", business_profit_cents=15_000_000,
                                wages_cents=15_000_000), 2026)
    assert joint.federal.se_tax_cents == 2_119_400
    single = annual_tax(TaxFacts(filing="single", ages=(44,), state="CA", business_profit_cents=15_000_000,
                                 wages_cents=15_000_000), 2026)
    assert single.federal.se_tax_cents < 2_119_400


def test_wages_by_person_must_match_the_filers_and_the_owner_must_be_one_of_them():
    with pytest.raises(InputError):
        annual_tax(TaxFacts(filing="mfj", ages=(44, 42), state="CA", ss_wages_by_person_cents=(1,)), 2026)
    with pytest.raises(InputError):
        annual_tax(TaxFacts(filing="mfj", ages=(44, 42), state="CA", business_owner=2), 2026)
    with pytest.raises(InputError):
        annual_tax(TaxFacts(filing="single", ages=(44,), state="CA", ss_wages_by_person_cents=(-1,)), 2026)
