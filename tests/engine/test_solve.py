from dataclasses import replace

import numpy as np
import pytest

from steward.engine import solver as sv
from steward.engine.inputs import Bucket, Levers, Mix, Person
from steward.engine.market import Histories
from steward.engine.simulate import prepare
from steward.engine.synthetic import synthetic_household
from steward.engine.tax import rules

CASH = Mix(0.0, 0.0, 1.0)


def flat(hh, n_hist=8):
    prep = prepare(hh, n_hist=n_hist)
    zeros = np.zeros((n_hist, prep.n_years))
    return replace(prep, hist=Histories(stock=zeros, bond=zeros, cash=zeros, source_index=zeros.astype(np.int64)))


@pytest.fixture(scope="module")
def prepared_small():
    return prepare(synthetic_household().household, n_hist=300)


def test_candidate_ages_run_from_now_to_70():
    assert sv.candidate_ages(synthetic_household().household) == list(range(44, 71))
    assert sv.candidate_ages(synthetic_household(jr=Person(1956, "male")).household) == [70]
    assert sv.candidate_ages(synthetic_household(jr=Person(1955, "male")).household) == []


def test_first_and_fractional_age():
    s = ((60, 0.50), (61, 0.70), (62, 0.95), (63, 0.99))
    assert sv.first_age(s, 0.90) == 62 and sv.first_age(s, 0.80) == 62 and sv.first_age(s, 0.999) is None
    assert sv.fractional_age(s, 0.90) == pytest.approx(61.8)
    assert sv.fractional_age(s, 0.60) == pytest.approx(60.5)
    assert sv.fractional_age(s, 0.40) == 60.0           # already above the threshold at the first age
    assert sv.fractional_age(s, 0.999) is None


def test_zero_volatility_zero_inflation_matches_a_hand_computed_drawdown():
    # both 60, $50,000 a year, $1,600,000 in cash, Medicare for two from 65, no Social Security, no returns
    inputs = synthetic_household(
        jr=Person(1966, "male"), spouse=Person(1966, "female"), salary_cents=0, k401_pct_bp=0, match_rate_bp=0, match_cap_bp=0,
        spending_basis_cents=5_000_000, surplus_cents=0, mortgage_payment_cents=0, mortgage_payoff_year=None, health_premium_cents=0,
        cash=Bucket(160_000_000, CASH), taxable=Bucket(0, CASH), traditional=Bucket(0, CASH), roth=Bucket(0, CASH), hsa=Bucket(0, CASH),
        children=(),
    )
    hh = inputs.household
    part_b = rules.table("medicare", 2026)["part_b_monthly"] * 12
    # by hand: retiring at R leaves 95 - R years of spending; every retirement year costs 50,000 + 2 x Part B (both are 65+ from 2031)
    def lasts(R):
        cash = 1_600_000.0
        for age in range(R, 95):
            cash -= 50_000 + (2 * part_b if age >= 65 else 0)
        return cash >= 0
    expected = [1.0 if lasts(R) else 0.0 for R in range(60, 71)]
    assert expected == [0.0] * 6 + [1.0] * 5         # $1.6M lasts 29 years at $54,869.60 but not 30

    res = sv.solve(inputs, prepared=flat(hh))
    assert [r for _, r in res.success_by_age] == expected
    assert res.comfortable_age == res.likely_age == 66 and res.comfortable_year == 2032
    assert res.band_age == 66
    # the band at age 66: flat $1.6M for six working years, then the hand-computed drawdown; percentiles coincide
    p50 = [b.p50_cents for b in res.band]
    assert p50[:7] == [160_000_000] * 7
    assert p50[10] == pytest.approx(round((1_600_000 - 4 * (50_000 + 2 * part_b)) * 100), abs=100)   # money arrays are float32: about a dollar
    assert all(b.p10_cents == b.p50_cents == b.p90_cents for b in res.band)
    assert len(res.band) == 36 and res.band[0].year == 2026 and res.band[0].jr_age == 60


def test_identical_inputs_give_identical_results(prepared_small):
    inputs = synthetic_household()
    a = sv.solve(inputs, prepared=prepared_small)
    b = sv.solve(inputs, prepared=prepared_small)
    assert a == b
    c = sv.solve(synthetic_household())          # fresh draws from the fixed seed, full size
    d = sv.solve(synthetic_household())
    assert c == d and c.histories == 2000


def test_synthetic_household_reaches_both_thresholds(prepared_small):
    res = sv.solve(synthetic_household(), prepared=prepared_small)
    assert res.likely_age is not None and res.comfortable_age is not None
    assert res.likely_age <= res.comfortable_age
    assert res.comfortable_year == 1982 + res.comfortable_age and res.band_age == res.comfortable_age
    assert len(res.success_by_age) == 27 and all(0.0 <= r <= 1.0 for _, r in res.success_by_age)
    assert len(res.band) == prepared_small.n_years + 1
    assert all(b.p10_cents <= b.p50_cents <= b.p90_cents for b in res.band)
    assert res.engine_version == "2026.10.5" and len(res.input_digest) == 16 and res.histories == 300


def test_saving_more_never_makes_an_age_later(prepared_small):
    inputs = synthetic_household()
    base = sv.solve(inputs, prepared=prepared_small)
    more = sv.solve(inputs, Levers(save_more_monthly_cents=50_000), prepared=prepared_small)
    assert all(m >= b for (_, b), (_, m) in zip(base.success_by_age, more.success_by_age))
    assert more.comfortable_age <= base.comfortable_age and more.likely_age <= base.likely_age


def test_spending_more_never_makes_an_age_earlier(prepared_small):
    inputs = synthetic_household()
    base = sv.solve(inputs, prepared=prepared_small)
    more = sv.solve(inputs, Levers(spending_pct=110), prepared=prepared_small)
    assert all(m <= b for (_, b), (_, m) in zip(base.success_by_age, more.success_by_age))
    if more.comfortable_age is not None:
        assert more.comfortable_age >= base.comfortable_age
    if more.likely_age is not None:
        assert more.likely_age >= base.likely_age


def test_jr_past_70_gives_no_ages_and_says_so():
    res = sv.solve(synthetic_household(jr=Person(1955, "male"), spouse=Person(1960, "female")))
    assert res.comfortable_age is None and res.likely_age is None and res.band == () and res.band_age is None
    assert "{person1} is past 70; no retirement ages were tested." in res.assumptions


def test_restricting_ages_restricts_the_result(prepared_small):
    res = sv.solve(synthetic_household(), ages=[60, 61, 62], prepared=prepared_small)
    assert [a for a, _ in res.success_by_age] == [60, 61, 62]
    assert res.band_age in (60, 61, 62)


def test_solving_without_the_band_gives_the_same_ages_and_skips_the_balances(prepared_small):
    inputs = synthetic_household()
    full = sv.solve(inputs, prepared=prepared_small)
    lean = sv.solve(inputs, prepared=prepared_small, band=False)
    assert lean.band == () and lean.band_age is None and full.band
    assert replace(lean, band=full.band, band_age=full.band_age) == full
    ages = [70, 50, 60]                                    # out of order: success comes back in the caller's order either way
    tracked = sv.simulate(inputs, inputs.levers, ages, prepared_small)
    untracked = sv.simulate(inputs, inputs.levers, ages, prepared_small, track_investable=False)
    assert untracked.investable is None and np.array_equal(untracked.success, tracked.success)


def test_assumptions_are_plain_words_and_name_every_rule():
    inputs = synthetic_household(spending_months=7, stale_notes=("The savings balance was last updated 120 days ago.",),
                                 default_mix_symbols=("XYZ",), spouse=Person(1984, "female"))
    res = sv.solve(inputs, prepared=prepare(inputs.household, n_hist=20))
    text = "\n".join(res.assumptions)
    assert "20 histories" in text
    assert "1928" in text and "2025" in text and "Damodaran" in text and "8 years" in text
    assert "17%" in text and "2034" in text and "2026 Trustees Report" in text
    assert "2026 federal" in text and "2025 California" in text
    assert "Based on 7 months" in text
    assert sv.D11_LINE in res.assumptions                                            # one plain line (spec 3.5)
    assert sv.D10_LINE in res.assumptions
    no_mortgage = sv.solve(synthetic_household(mortgage_payment_cents=0, mortgage_payoff_year=None),
                           prepared=prepare(inputs.household, n_hist=20))
    assert sv.D10_LINE not in no_mortgage.assumptions
    assert "taxed on its own" not in text
    assert "last updated 120 days ago" in text and "XYZ" in text
    assert "No earnings record for {person2}" in text
    assert "95" in text and "does not drop after a death" in text
    full = sv.solve(replace(inputs, levers=Levers(full_ss_benefits=True)), prepared=prepare(inputs.household, n_hist=20))
    assert "Full Social Security benefits" in "\n".join(full.assumptions)
    other_state = sv.solve(synthetic_household(state="NY"), prepared=prepare(synthetic_household(state="NY").household, n_hist=20))
    assert "State tax isn't calculated for New York yet." in other_state.assumptions
    assert "flat 5%" not in "\n".join(other_state.assumptions)
    texas = sv.solve(synthetic_household(state="TX"), prepared=prepare(synthetic_household(state="TX").household, n_hist=20))
    assert "Texas has no income tax on wages" in "\n".join(texas.assumptions)


def test_digest_is_the_same_whether_college_levels_are_left_out_or_spelled_out():
    s = synthetic_household()
    prep = flat(s.household, n_hist=4)
    explicit = tuple(c.cost_level for c in s.household.children)
    assert sv.solve(s, prepared=prep, band=False).input_digest == \
        sv.solve(s, Levers(college_levels=explicit), prepared=prep, band=False).input_digest


def test_mortgage_paid_off_this_year_is_stated():
    inputs = synthetic_household(mortgage_payoff_year=2026)
    res = sv.solve(inputs, prepared=prepare(inputs.household, n_hist=50))
    assert any("The mortgage is paid off in 2026" in a for a in res.assumptions)


def test_the_taxes_line_says_when_the_federal_rules_are_the_latest_earlier_ones():
    # Final review minor 4: from January 2027 the plan uses 2026 federal rules until 2027's are published
    hh = replace(synthetic_household().household, plan_year=2027)
    text = "\n".join(sv.build_assumptions(hh, Levers(), 8))
    assert "Taxes: 2026 federal rules (the latest published)" in text
    now = "\n".join(sv.build_assumptions(replace(hh, plan_year=2026), Levers(), 8))
    assert "Taxes: 2026 federal rules and" in now or "Taxes: 2026 federal rules;" in now


def test_the_college_assumption_names_the_share_living_costs_and_both_lengths():
    from steward.engine.levers import clamp
    from steward.engine.solver import COLLEGE_LINE, build_assumptions
    hh = synthetic_household().household
    assert COLLEGE_LINE in build_assumptions(hh, clamp(Levers(), hh), 300)
    assert COLLEGE_LINE == (
        "College: College Board 2025-26 costs for each child's school (tuition and fees, and living costs where chosen), "
        "at the share you plan to cover, growing 1% a year above inflation, for two years from 18 (trade or community "
        "college) or four; the 529 pays first, and 529 contributions continue while {person1} works and the child is under 18.")


def test_an_estimated_record_says_so_in_the_assumptions():
    from dataclasses import replace
    from steward.engine.levers import clamp
    from steward.engine.solver import ESTIMATE_LINE, build_assumptions
    hh = synthetic_household().household
    est = replace(hh, jr=replace(hh.jr, estimated=True))
    assert ESTIMATE_LINE in build_assumptions(est, clamp(Levers(), est), 300)
    assert ESTIMATE_LINE not in build_assumptions(hh, clamp(Levers(), hh), 300)
    assert ESTIMATE_LINE == ("No earnings record for {person1}: their Social Security is estimated from today's salary, as if their "
                             "pay had followed the national average wage since 22.")
