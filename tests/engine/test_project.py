"""project() (spec 3.4 and 9): projections with known answers. Fictional people only: Margaret Ellis is the demo
parent, born 1944, filing single in California."""
import pytest

from steward.engine.inputs import InputError
from steward.engine.project import (
    Assumptions, Expense, HomeSale, Income, LtcPolicy, ProjectionInputs, ltc_runs_out, money_lasts_until, project,
)
from steward.engine.tax import TaxFacts, annual_tax

FLAT = Assumptions(inflation=0.0, real_return=0.0, care_inflation=0.0)


def margaret(**overrides) -> ProjectionInputs:
    base = dict(start_year=2026, filing="single", state="CA", birth_years=(1944,))
    base.update(overrides)
    return ProjectionInputs(**base)


def test_a_fixed_balance_and_spending_run_out_in_a_known_year():
    # $100,000 in cash, $30,000 a year of spending, nothing coming in, no growth: 2026-2028 are paid, 2029 is $20,000 short
    rows = project(margaret(cash_cents=10_000_000, expenses=(Expense("Spending", 3_000_000, 2026),)), FLAT, 6)
    assert [r.shortfall_cents for r in rows[:3]] == [0, 0, 0]
    assert rows[3].shortfall_cents == 2_000_000 and rows[3].withdrawals_cents == 1_000_000
    assert money_lasts_until(rows) == 2028
    assert rows[2].balance_cents == 1_000_000 and all(r.tax_cents == 0 for r in rows)   # cash withdrawals aren't income
    assert money_lasts_until(project(margaret(cash_cents=10_000_000_000, expenses=(Expense("Spending", 3_000_000, 2026),)), FLAT, 6)) is None


def test_long_term_care_insurance_pays_after_the_wait_until_the_pool_is_used():
    # care at $120,000 a year from 2027; $200 a day after 90 days; a $219,000 pool (three years of $73,000)
    pol = LtcPolicy(care_start_year=2027, benefit_daily_cents=20_000, waiting_days=90, total_benefit_cents=21_900_000)
    p = margaret(cash_cents=100_000_000_000, expenses=(Expense("Assisted living", 12_000_000, 2027, kind="care", medical=True),),
                 ltc_policies=(pol,))
    rows = project(p, FLAT, 6)
    assert [r.ltc_benefit_cents for r in rows] == [0, 5_500_000, 7_300_000, 7_300_000, 1_800_000, 0]
    assert ltc_runs_out(rows) == 2030 and rows[4].ltc_pool_cents == 0
    assert rows[1].care_cents == 12_000_000


def test_the_premium_stops_once_the_policy_pays():
    # waiver of premium: the $3,650 a year premium is in spending; it stops for the 275 days the policy pays in 2027,
    # and every year after (once the pool is used up the policy has ended, so there's no premium either)
    pol = LtcPolicy(care_start_year=2027, benefit_daily_cents=20_000, waiting_days=90, total_benefit_cents=21_900_000,
                    premium_yearly_cents=365_000)
    p = margaret(cash_cents=100_000_000_000, ltc_policies=(pol,),
                 expenses=(Expense("Spending", 4_000_000, 2026),
                           Expense("Assisted living", 12_000_000, 2027, kind="care", medical=True)))
    rows = project(p, FLAT, 6)
    assert [r.expenses_cents for r in rows] == [4_000_000, 15_725_000, 15_635_000, 15_635_000, 15_635_000, 15_635_000]
    unpaid = project(margaret(cash_cents=100_000_000_000, ltc_policies=(pol,),
                              expenses=(Expense("Spending", 4_000_000, 2026),)), FLAT, 3)
    assert [r.expenses_cents for r in unpaid] == [4_000_000] * 3          # no care, nothing paid, the premium goes on


def test_a_policy_without_an_inflation_rider_buys_less_care_each_year():
    pol = LtcPolicy(care_start_year=2026, benefit_daily_cents=20_000, waiting_days=0, benefit_years=10)
    p = margaret(cash_cents=100_000_000_000, expenses=(Expense("Care", 20_000_000, 2026, kind="care", medical=True),),
                 ltc_policies=(pol,))
    rows = project(p, Assumptions(inflation=0.025, real_return=0.0, care_inflation=0.04), 3)
    assert [r.ltc_benefit_cents for r in rows] == [7_300_000, round(7_300_000 / 1.025), round(7_300_000 / 1.025 ** 2)]
    rider = project(margaret(cash_cents=100_000_000_000, ltc_policies=(LtcPolicy(2026, 20_000, None, 0, None, 10, 0.025),),
                             expenses=(Expense("Care", 20_000_000, 2026, kind="care", medical=True),)),
                    Assumptions(inflation=0.025, real_return=0.0), 3)
    assert [r.ltc_benefit_cents for r in rider] == [7_300_000] * 3


def test_a_home_sale_lands_in_its_year_and_only_the_gain_over_the_exclusion_is_taxed():
    # sold in 2028 for $800,000 less 6%: $752,000 arrives; the gain over the $300,000 basis is $452,000, of which
    # $250,000 is excluded for a single filer, so $202,000 is a long-term gain on the 2028 return
    p = margaret(cash_cents=5_000_000, home_sale=HomeSale(2028, 80_000_000, 30_000_000),
                 expenses=(Expense("Spending", 2_000_000, 2026),))
    rows = project(p, FLAT, 4)
    assert [r.home_sale_cents for r in rows] == [0, 0, 75_200_000, 0]
    assert rows[2].tax.agi_cents == 20_200_000
    want = annual_tax(TaxFacts(filing="single", ages=(84,), state="CA", long_term_gains_cents=20_200_000), 2028).total_tax_cents
    assert rows[2].tax_cents == want and rows[1].tax_cents == 0
    assert rows[2].saved_cents == 75_200_000 - 2_000_000 - want


def test_withdrawals_from_the_ira_also_pay_their_own_tax():
    # $60,000 a year of spending, all from a traditional IRA: what's withdrawn less its tax covers the spending to $1
    p = margaret(birth_years=(1960,), traditional_cents=200_000_000, expenses=(Expense("Spending", 6_000_000, 2026),))
    row = project(p, FLAT, 1)[0]
    assert row.withdrawals_cents - row.tax_cents == pytest.approx(6_000_000, abs=100)
    exact = annual_tax(TaxFacts(filing="single", ages=(66,), state="CA", ira_distributions_cents=row.withdrawals_cents), 2026)
    assert row.tax_cents == exact.total_tax_cents and row.shortfall_cents == 0


def test_rmds_are_forced_and_what_isnt_needed_is_saved():
    # Margaret is 82: the RMD on $500,000 is 500,000 / 18.5 = $27,027.03; spending is $10,000 from Social Security
    p = margaret(traditional_cents=50_000_000, incomes=(Income("Social Security", 2_400_000, 2026, kind="social_security"),),
                 expenses=(Expense("Spending", 1_000_000, 2026),))
    row = project(p, FLAT, 1)[0]
    assert row.rmd_cents == round(50_000_000 / 18.5)
    assert row.saved_cents == 2_400_000 + row.rmd_cents - 1_000_000 - row.tax_cents
    assert row.taxable_cents == row.saved_cents and row.withdrawals_cents == 0


def test_the_mortgage_shrinks_by_inflation_and_care_grows_at_its_own_rate():
    p = margaret(cash_cents=1_000_000_000, expenses=(Expense("Mortgage", 2_400_000, 2026, 2035, growth="fixed_dollars", kind="mortgage"),
                                                     Expense("Care", 6_000_000, 2026, growth="care", kind="care")))
    rows = project(p, Assumptions(inflation=0.025, real_return=0.0, care_inflation=0.04), 3)
    for t, r in enumerate(rows):
        assert r.expenses_cents == round(2_400_000 / 1.025 ** t + 6_000_000 * (1.04 / 1.025) ** t)
        assert r.care_cents == round(6_000_000 * (1.04 / 1.025) ** t)


def test_care_costs_bring_in_the_medical_deduction():
    p = margaret(traditional_cents=100_000_000, incomes=(Income("Social Security", 2_800_000, 2026, kind="social_security"),),
                 expenses=(Expense("Assisted living", 7_200_000, 2026, kind="care", medical=True),))
    row = project(p, FLAT, 1)[0]
    assert row.tax.itemized and any("medical deduction" in line for line in row.tax.explain)


def test_bad_inputs_are_refused_in_plain_words():
    with pytest.raises(InputError, match="one birth year"):
        project(margaret(birth_years=(1944, 1946)), FLAT, 5)
    with pytest.raises(InputError, match="1 to 80 years"):
        project(margaret(), FLAT, 0)
    with pytest.raises(InputError, match="ends before it starts"):
        project(margaret(expenses=(Expense("Spending", 100, 2030, 2028),)), FLAT, 5)
    with pytest.raises(InputError, match="daily or a monthly benefit"):
        project(margaret(expenses=(Expense("Care", 100, 2026, kind="care"),), ltc_policies=(LtcPolicy(2026, total_benefit_cents=1),)), FLAT, 2)


def test_a_long_projection_runs_past_120_and_children_not_yet_born_are_left_off():
    # Review Focus 1: Margaret (born 1944) projected 80 years is 161 at the end; the return caps ages at 120
    rows = project(margaret(cash_cents=10_000_000_000, incomes=(Income("Pension", 1_000_000, 2026),),
                            dependents=(2030,)), FLAT, 80)
    assert len(rows) == 80 and rows[-1].ages == (161,) and rows[-1].tax.over_65_deduction_cents == 0
    assert rows[0].tax.credits_cents == 0                              # the 2030 dependent isn't born in 2026


def test_running_out_in_a_year_with_tax_due_reports_a_shortfall_and_no_negative_balance():
    # Review Focus 2: $50,000 in an IRA, $60,000 of spending: the IRA is emptied, its tax is owed, the rest is short
    rows = project(margaret(birth_years=(1960,), traditional_cents=5_000_000, expenses=(Expense("Spending", 6_000_000, 2026),)), FLAT, 2)
    first = rows[0]
    assert first.withdrawals_cents == 5_000_000 and first.shortfall_cents > 1_000_000
    assert first.tax_cents == annual_tax(TaxFacts(filing="single", ages=(66,), state="CA", ira_distributions_cents=5_000_000), 2026).total_tax_cents
    assert min(first.cash_cents, first.taxable_cents, first.traditional_cents, first.roth_cents) >= 0
    assert money_lasts_until(rows) == 2025


def _business_streams(rng):
    """How part 2 feeds a ProfitRange to the engine (part 3 ruling I3): Schedule C profit (mid) is what is taxed,
    and the gap to the cash profit (mid vs cash_mid) is plain money in or out with no tax."""
    streams_in = [Income("Consulting", rng.mid_cents, 2026, kind="business")]
    streams_out = []
    if rng.cash_mid_cents >= rng.mid_cents:
        streams_in.append(Income("Home office and mileage", rng.cash_mid_cents - rng.mid_cents, 2026, kind="nontaxable"))
    else:
        streams_out.append(Expense("Meals counted in full in cash", rng.mid_cents - rng.cash_mid_cents, 2026, kind="other"))
    return tuple(streams_in), tuple(streams_out)


def test_business_money_in_is_cash_profit_but_tax_is_on_schedule_c_profit():
    # Part 3 ruling I3: the plan's money in is the cash profit; the tax is on the Schedule C profit (after the home
    # office and mileage), so those deductions are not taxed again at the household's marginal rate.
    from steward.business.report import ProfitRange
    rng = ProfitRange(year=2026, ytd_cents=3_000_000, low_cents=6_000_000, high_cents=8_000_000, entered=True,
                      cash_ytd_cents=3_500_000, cash_low_cents=7_000_000, cash_high_cents=9_000_000)
    assert (rng.mid_cents, rng.cash_mid_cents) == (7_000_000, 8_000_000)
    inc, exp = _business_streams(rng)
    p = ProjectionInputs(start_year=2026, filing="single", state="CA", birth_years=(1980,),
                         incomes=inc, expenses=exp + (Expense("Spending", 5_000_000, 2026),))
    row = project(p, FLAT, 1)[0]
    assert row.income_cents == rng.cash_mid_cents
    want = annual_tax(TaxFacts(filing="single", ages=(46,), state="CA", business_profit_cents=rng.mid_cents), 2026)
    assert row.tax_cents == want.total_tax_cents > 0
    over = annual_tax(TaxFacts(filing="single", ages=(46,), state="CA", business_profit_cents=rng.cash_mid_cents), 2026)
    assert row.tax_cents < over.total_tax_cents


def test_business_cash_below_schedule_c_profit_still_taxes_schedule_c_profit():
    # Meals counted in full in cash make cash profit lower than Schedule C profit: the gap is an expense, not a tax cut.
    from steward.business.report import ProfitRange
    rng = ProfitRange(year=2026, ytd_cents=3_000_000, low_cents=7_000_000, high_cents=9_000_000, entered=True,
                      cash_ytd_cents=2_500_000, cash_low_cents=6_000_000, cash_high_cents=8_000_000)
    assert (rng.mid_cents, rng.cash_mid_cents) == (8_000_000, 7_000_000)
    inc, exp = _business_streams(rng)
    p = ProjectionInputs(start_year=2026, filing="single", state="CA", birth_years=(1980,),
                         incomes=inc, expenses=exp, cash_cents=0)
    row = project(p, FLAT, 1)[0]
    want = annual_tax(TaxFacts(filing="single", ages=(46,), state="CA", business_profit_cents=rng.mid_cents), 2026)
    assert row.tax_cents == want.total_tax_cents > 0
    assert row.income_cents - (rng.mid_cents - rng.cash_mid_cents) == rng.cash_mid_cents


def test_self_employment_tax_counts_only_the_business_owners_own_wages():
    # Final review I1: one spouse's wages don't use up the other's Social Security wage base
    p = ProjectionInputs(start_year=2026, filing="mfj", state="CA", birth_years=(1982, 1984), cash_cents=100_000_000,
                         incomes=(Income("Consulting", 15_000_000, 2026, kind="business", owner=0),
                                  Income("Salary", 15_000_000, 2026, kind="wages", owner=1)))
    row = project(p, FLAT, 1)[0]
    assert row.tax.federal.se_tax_cents == 2_119_400
    mine = ProjectionInputs(start_year=2026, filing="mfj", state="CA", birth_years=(1982, 1984), cash_cents=100_000_000,
                            incomes=(Income("Consulting", 15_000_000, 2026, kind="business", owner=0),
                                     Income("Salary", 15_000_000, 2026, kind="wages", owner=0)))
    assert project(mine, FLAT, 1)[0].tax.federal.se_tax_cents < 2_119_400


def test_an_income_owner_must_be_on_the_return_and_one_person_owns_the_business():
    with pytest.raises(InputError):
        project(margaret(incomes=(Income("Pension", 100, 2026, owner=1),)), FLAT, 1)
    two = ProjectionInputs(start_year=2026, filing="mfj", state="CA", birth_years=(1982, 1984),
                           incomes=(Income("A", 100, 2026, kind="business", owner=0), Income("B", 100, 2026, kind="business", owner=1)))
    with pytest.raises(InputError):
        project(two, FLAT, 1)


def test_an_itemizer_deducts_last_years_state_income_tax():
    # Final review minor 8: the state income tax paid in a year (taken as last year's) is a federal SALT deduction
    p = margaret(cash_cents=100_000_000, incomes=(Income("Pension", 20_000_000, 2026, kind="pension"),),
                 expenses=(Expense("Care", 10_000_000, 2026, kind="care", medical=True),))
    first, second = project(p, FLAT, 2)
    assert first.tax.itemized and first.tax.state.tax_cents > 0
    want = annual_tax(TaxFacts(filing="single", ages=(83,), state="CA", pensions_cents=20_000_000, medical_cents=10_000_000,
                               state_income_tax_cents=first.tax.state.tax_cents), 2027, marginal=False)
    assert second.tax.total_tax_cents == want.total_tax_cents < first.tax.total_tax_cents


def test_marginal_from_fills_the_marginal_rate_from_that_year_and_changes_nothing_else():
    from dataclasses import replace
    p = margaret(traditional_cents=50_000_000, incomes=(Income("Social Security", 3_000_000, 2026, kind="social_security"),),
                 expenses=(Expense("Spending", 5_000_000, 2026),))
    plain = project(p, FLAT, 5)
    rated = project(p, FLAT, 5, marginal_from=2028)
    assert [r.tax.marginal_rate for r in plain] == [0.0] * 5
    assert [r.tax.marginal_rate for r in rated[:2]] == [0.0, 0.0] and all(r.tax.marginal_rate > 0 for r in rated[2:])
    strip = lambda rows: [replace(r, tax=replace(r.tax, marginal_rate=0.0)) for r in rows]  # noqa: E731
    assert strip(rated) == strip(plain)
