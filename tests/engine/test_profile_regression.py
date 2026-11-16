"""The engine keeps today's numbers for a household that sets nothing new (profile spec, College costs; Global
Constraints): every kid at 100% with living costs, at a four-year level. The figures were computed on main b072bee,
before any Profile change, by .superpowers/sdd/2026-10-29-steward-profile-household/pin.py: a SHA-256 of the
investable paths, the success rates, a batched run of two level sets, and the college lever's try values and impacts."""
import hashlib
from dataclasses import replace

import numpy as np

from steward.engine.impacts import lever_impacts
from steward.engine.inputs import Bucket, Child, Levers, Mix
from steward.engine.levers import ObservedTry, clamp, default_try
from steward.engine.simulate import prepare, simulate, trial_success_rates
from steward.engine.synthetic import synthetic_household

KIDS = (
    Child("Teen", 2009, "private", Bucket(2_000_000, Mix(0.6, 0.4, 0.0, 10)), 20_000),
    Child("Middle", 2014, "out_of_state_public", Bucket(1_500_000, Mix(0.7, 0.3, 0.0, 10)), 30_000),
    Child("Youngest", 2019, "in_state_public", Bucket(500_000, Mix(0.8, 0.2, 0.0, 10)), 25_000),
)


def test_a_household_that_sets_nothing_new_keeps_main_s_numbers():
    inputs = synthetic_household(children=KIDS)
    hh = inputs.household
    prep = prepare(hh, n_hist=200)
    out = simulate(inputs, inputs.levers, [55, 60, 65], prep)
    assert hashlib.sha256(out.investable.astype(np.float32).tobytes()).hexdigest()[:16] == "064b20892a0bb6eb"
    assert out.success.mean(axis=0).tolist() == [0.23, 0.75, 0.975]
    trials = [Levers(college_levels=("in_state_public",) * 3), Levers(college_levels=("private",) * 3)]
    assert trial_success_rates(inputs, trials, [55, 60, 65], prep, stop_below=0.0).tolist() == [
        [0.45, 0.87, 0.995], [0.135, 0.63, 0.95]]
    tr, _ = default_try(hh, clamp(inputs.levers, hh), ObservedTry())
    assert tr.college_levels == ("out_of_state_public", "in_state_public", "in_state_public")
    rows = [(i.child_label, i.try_value, i.delta_months) for i in lever_impacts(inputs, tr, prepared=prep) if i.key == "college"]
    assert rows == [("Middle", "in_state_public", -6), ("Teen", "out_of_state_public", -1), ("Youngest", "in_state_public", 0)]


def test_spelling_out_the_defaults_is_the_same_household():
    plain = synthetic_household(children=KIDS)
    spelled = synthetic_household(children=tuple(replace(c, share_pct=100, covers_living=True) for c in KIDS))
    prep = prepare(plain.household, n_hist=50)
    a = simulate(plain, plain.levers, [60], prep)
    b = simulate(spelled, spelled.levers, [60], prep)
    assert np.array_equal(a.investable, b.investable) and np.array_equal(a.success, b.success)
