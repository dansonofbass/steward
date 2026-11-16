from dataclasses import replace

import numpy as np
import pytest

from steward.engine import solver as sv
from steward.engine.impacts import LeverImpact, delta_months, lever_impacts
from steward.engine.inputs import Levers
from steward.engine.levers import ObservedTry, default_try, with_try
from steward.engine.simulate import prepare
from steward.engine.solver import candidate_ages
from steward.engine.synthetic import synthetic_household


@pytest.fixture(scope="module")
def world():
    inputs = synthetic_household()
    prep = prepare(inputs.household, n_hist=300)
    base = sv.solve(inputs, prepared=prep)
    trial, _ = default_try(inputs.household, inputs.levers, ObservedTry(consulting_12mo_cents=600_000, gift_12mo_cents=1_000_000, spouse_earnings_cents=6_000_000))
    return inputs, prep, base, trial


def test_one_impact_per_lever_and_per_child_sorted_by_size(world):
    inputs, prep, base, trial = world
    impacts = lever_impacts(inputs, trial, base=base, prepared=prep)
    keys = [i.key for i in impacts]
    assert sorted(keys) == sorted(["save_more", "spending", "consulting", "gift", "spouse_earnings", "jr_claim", "spouse_claim", "college", "college", "college", "full_ss"])
    assert sorted(i.child_label for i in impacts if i.key == "college") == ["Middle", "Oldest", "Youngest"]
    assert all(i.child_label is None for i in impacts if i.key != "college")
    sizes = [abs(i.delta_months) for i in impacts if i.delta_months is not None]
    assert sizes == sorted(sizes, reverse=True)
    assert all(isinstance(i, LeverImpact) and i.text for i in impacts)


def test_helpful_levers_never_push_the_age_later(world):
    inputs, prep, base, trial = world
    by_key = {(i.key, i.child_label): i for i in lever_impacts(inputs, trial, base=base, prepared=prep)}
    for key in ("save_more", "spending", "consulting", "gift", "spouse_earnings", "full_ss"):
        assert by_key[(key, None)].delta_months is not None and by_key[(key, None)].delta_months <= 0, key
    for child in ("Oldest", "Middle", "Youngest"):
        assert by_key[("college", child)].delta_months == 0 and by_key[("college", child)].text == "No change"   # already the lowest level


def test_unchanged_lever_reports_no_change(world):
    inputs, prep, base, _ = world
    same = Levers(jr_claim_age=67)                                     # equal to the assumed value
    impacts = {i.key: i for i in lever_impacts(inputs, same, base=base, prepared=prep)}
    assert impacts["jr_claim"].delta_months == 0 and impacts["jr_claim"].text == "No change"
    assert impacts["jr_claim"].comfortable_age == base.comfortable_age


def test_impacts_are_deterministic_and_match_a_full_solve(world):
    inputs, prep, base, trial = world
    a = lever_impacts(inputs, trial, base=base, prepared=prep)
    b = lever_impacts(inputs, trial, base=base, prepared=prep)
    assert a == b
    saving = next(i for i in a if i.key == "save_more")
    full = sv.solve(inputs, Levers(save_more_monthly_cents=trial.save_more_monthly_cents), prepared=prep)
    assert saving.comfortable_age == full.comfortable_age
    assert saving.delta_months == delta_months(base.success_by_age, full.success_by_age)
    ages = candidate_ages(inputs.household)
    for imp in a:
        lv = with_try(inputs.levers, trial, imp.key, children=inputs.household.children,
                      child_index=None if imp.child_label is None else [c.label for c in inputs.household.children].index(imp.child_label))
        if lv == inputs.levers:
            continue
        ref = sv.solve(inputs, lv, ages=ages, prepared=prep)
        assert imp.comfortable_age == ref.comfortable_age, (imp.key, imp.child_label)
        assert imp.delta_months == delta_months(base.success_by_age, ref.success_by_age), (imp.key, imp.child_label)


def test_not_comfortable_by_70_ranks_the_none_group():
    inputs = synthetic_household(spending_basis_cents=22_000_000)
    prep = prepare(inputs.household, n_hist=300)
    base = sv.solve(inputs, prepared=prep)
    assert base.comfortable_age is None
    trial, _ = default_try(inputs.household, inputs.levers, ObservedTry(consulting_12mo_cents=600_000, gift_12mo_cents=1_000_000, spouse_earnings_cents=6_000_000))
    trial = replace(trial, college_levels=("private",) * 3)    # a real change on every row, so no "No change" rows
    impacts = lever_impacts(inputs, trial, base=base, prepared=prep)
    assert all(i.delta_months is None for i in impacts)
    aged = [i.comfortable_age for i in impacts if i.comfortable_age is not None]
    n = len(aged)
    assert 0 < n < len(impacts), [(i.key, i.comfortable_age) for i in impacts]   # both groups present, so the ranking is tested
    assert len(set(aged)) >= 2
    assert all(i.comfortable_age is not None for i in impacts[:n]) and all(i.comfortable_age is None for i in impacts[n:])
    assert aged == sorted(aged)
    assert all(i.text == f"Comfortable by {i.comfortable_age}" for i in impacts[:n])
    assert all(i.text in ("Still not by 70", "No change") for i in impacts[n:])


def test_spending_more_is_reported_later(world):
    inputs, prep, base, _ = world
    impacts = {i.key: i for i in lever_impacts(inputs, Levers(spending_pct=120), base=base, prepared=prep)}
    assert impacts["spending"].delta_months is None or impacts["spending"].delta_months >= 0
    assert impacts["spending"].try_value == 120


def test_a_moved_age_never_reads_no_change_and_months_round_half_away_from_zero():
    from steward.engine.impacts import round_months
    from steward.engine.levers import impact_text
    base_rates = ((61, 0.8995), (62, 0.95))     # comfortable at 62, interpolated 61.0099
    new_rates = ((61, 0.90), (62, 0.95))        # comfortable at 61, interpolated 61.0: under a month earlier
    delta = delta_months(base_rates, new_rates)
    assert delta == -1
    assert impact_text(delta, 62, 61) == "about 1 month earlier"
    assert delta_months(new_rates, base_rates) == 1
    assert round_months(-2.5) == -3 and round_months(2.5) == 3 and round_months(0.49) == 0 and round_months(-0.5) == -1
    assert delta_months(base_rates, ((61, 0.5), (62, 0.6))) is None


def _try_for(inputs, all_private=False):
    trial, _ = default_try(inputs.household, inputs.levers, ObservedTry(consulting_12mo_cents=600_000, gift_12mo_cents=1_000_000, spouse_earnings_cents=6_000_000))
    return replace(trial, college_levels=("private",) * len(inputs.household.children)) if all_private else trial


@pytest.mark.parametrize("overrides, all_private, n_hist", [
    ({}, False, 2_000),                                    # the synthetic household, as the perf budget times it
    ({"spending_basis_cents": 22_000_000}, True, 2_000),   # not comfortable by 70, every row a real change
    ({"spending_basis_cents": 12_000_000}, False, 300),
    ({"spending_basis_cents": 6_000_000}, True, 300),
    ({"spending_basis_cents": 22_000_000}, False, 300),
])
def test_batched_impacts_equal_the_per_trial_reference(overrides, all_private, n_hist):
    from steward.engine.impacts import _lever_impacts_per_trial
    inputs = synthetic_household(**overrides)
    prep = prepare(inputs.household, n_hist=n_hist)
    base = sv.solve(inputs, prepared=prep)
    trial = _try_for(inputs, all_private)
    assert lever_impacts(inputs, trial, base=base, prepared=prep) == _lever_impacts_per_trial(inputs, trial, base=base, prepared=prep)
    assert lever_impacts(inputs, trial, prepared=prep) == _lever_impacts_per_trial(inputs, trial, prepared=prep)


def test_batched_rates_are_the_solve_rates_except_doomed_columns():
    from steward.engine.levers import LEVERS, clamp
    from steward.engine.simulate import simulate, trial_success_rates
    inputs = synthetic_household(spending_basis_cents=12_000_000)
    hh = inputs.household
    prep = prepare(hh, n_hist=300)
    ages = candidate_ages(hh)
    assumed, trial = clamp(inputs.levers, hh), clamp(_try_for(inputs, True), hh)
    trials = [assumed] + [with_try(assumed, trial, s.key, children=hh.children, child_index=0 if s.key == "college" else None) for s in LEVERS]
    for keep_before in (True, False):
        got = trial_success_rates(inputs, trials, ages, prep, stop_below=sv.COMFORTABLE, keep_before_crossing=keep_before)
        for k, lv in enumerate(trials):
            ref = simulate(inputs, lv, ages, prep, track_investable=False).success.mean(axis=0)
            dropped = np.isnan(got[k])
            assert np.array_equal(got[k][~dropped], ref[~dropped])          # bit for bit
            assert (ref[dropped] < sv.COMFORTABLE).all()
            if keep_before:                                                  # the age before a crossing keeps its rate
                assert not (dropped[:-1] & (ref[1:] >= sv.COMFORTABLE)).any()
        if not keep_before:
            assert np.isnan(got).any()                                       # the early stop did happen
    some = trial_success_rates(inputs, trials, ages, prep, columns=[(3, 1), (5, 2)], stop_below=sv.COMFORTABLE)
    assert np.isnan(np.delete(some.ravel(), [1 * len(ages) + 3, 2 * len(ages) + 5])).all()
    assert some[1, 3] == simulate(inputs, trials[1], [ages[3]], prep, track_investable=False).success.mean()


def test_a_kid_the_household_covers_0_percent_gets_no_college_row():
    from steward.engine.impacts import _lever_impacts_per_trial
    from steward.engine.levers import clamp
    base = synthetic_household()
    kids = base.household.children
    kids = (replace(kids[0], cost_level="private", share_pct=0), replace(kids[1], cost_level="private"), kids[2])
    inputs = replace(base, household=replace(base.household, children=kids))
    hh = inputs.household
    prep = prepare(hh, n_hist=100)
    tr, _ = default_try(hh, clamp(inputs.levers, hh), ObservedTry())
    rows = lever_impacts(inputs, tr, prepared=prep)
    assert sorted(i.child_label for i in rows if i.key == "college") == ["Middle", "Youngest"]
    assert rows == _lever_impacts_per_trial(inputs, tr, prepared=prep)
