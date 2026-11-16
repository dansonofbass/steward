"""'What would change it' (spec section 3.6): each lever's effect at its try value on the comfortable
age, computed on the same histories as the baseline."""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from steward.engine.inputs import EngineInputs, Levers, validate
from steward.engine.levers import LEVERS, clamp, impact_text, try_value, with_try
from steward.engine.simulate import Prepared, prepare, trial_success_rates
from steward.engine.solver import COMFORTABLE, SolveResult, candidate_ages, first_age, fractional_age, solve

WINDOW = 4
WIDEN = 6


@dataclass(frozen=True)
class LeverImpact:
    key: str
    label: str
    child_label: str | None
    try_value: int | bool | str
    delta_months: int | None      # change in the interpolated comfortable age, in months; negative = earlier
    comfortable_age: int | None
    text: str


def round_months(x: float) -> int:
    """Round half away from zero (Task 8 ruling 3), not Python's round-half-to-even."""
    return int(math.copysign(math.floor(abs(x) + 0.5), x))


def delta_months(base_rates: Sequence[tuple[int, float]], new_rates: Sequence[tuple[int, float]]) -> int | None:
    """Change in the interpolated comfortable age, in whole months; negative = earlier. None if either never gets there.

    A change in the whole comfortable age is never reported as zero months: it reads one month the right way."""
    base_frac = fractional_age(base_rates, COMFORTABLE)
    frac = fractional_age(new_rates, COMFORTABLE)
    if frac is None or base_frac is None:
        return None
    delta = round_months((frac - base_frac) * 12)
    base_age, new_age = first_age(base_rates, COMFORTABLE), first_age(new_rates, COMFORTABLE)
    if delta == 0 and new_age != base_age:
        delta = -1 if new_age < base_age else 1
    return delta


def _solve_near(inputs: EngineInputs, levers: Levers, base_age: int | None, full_ages: list[int], prep: Prepared) -> SolveResult:
    """Solve a window of ages around the baseline answer, widening until the answer is inside it."""
    if base_age is None or base_age not in full_ages:
        return solve(inputs, levers, ages=full_ages, prepared=prep, band=False)
    centre = full_ages.index(base_age)
    lo, hi = max(0, centre - WINDOW), min(len(full_ages) - 1, centre + WINDOW)
    while True:
        res = solve(inputs, levers, ages=full_ages[lo:hi + 1], prepared=prep, band=False)
        age = res.comfortable_age
        if age is None and hi < len(full_ages) - 1:
            hi = min(hi + WIDEN, len(full_ages) - 1)
            continue
        if age is not None and age == full_ages[lo] and lo > 0:
            lo = max(lo - WIDEN, 0)
            continue
        return res


def _search(rates: np.ndarray, base_age: int | None, full_ages: list[int]) -> tuple[int, int, bool]:
    """_solve_near's window search, on one trial's (A,) rates over the candidate ages as far as they are known.

    Returns (lo, hi, settled): the index range the search has reached, and whether it ends there; when it does not, it
    still needs the rates in that range that have not been simulated. A dropped column (NaN) counts as known: it is
    below the threshold. Each column is independent of the others, so the rates of a window taken from a bigger run
    are the ones a solve of just that window gives."""
    if base_age is None or base_age not in full_ages:
        lo, hi = 0, len(full_ages) - 1
        return lo, hi, all(_known(rates, i) for i in range(lo, hi + 1))
    centre = full_ages.index(base_age)
    lo, hi = max(0, centre - WINDOW), min(len(full_ages) - 1, centre + WINDOW)
    while all(_known(rates, i) for i in range(lo, hi + 1)):
        age = first_age(_curve(rates, full_ages, lo, hi), COMFORTABLE)
        if age is None and hi < len(full_ages) - 1:
            hi = min(hi + WIDEN, len(full_ages) - 1)
        elif age is not None and age == full_ages[lo] and lo > 0:
            lo = max(lo - WIDEN, 0)
        else:
            return lo, hi, True
    return lo, hi, False


_UNRUN = -1.0   # a rate not yet simulated; NaN is a column dropped as doomed


def _known(rates: np.ndarray, i: int) -> bool:
    return bool(rates[i] != _UNRUN)


def _curve(rates: np.ndarray, full_ages: list[int], lo: int, hi: int) -> tuple[tuple[int, float], ...]:
    return tuple((full_ages[i], float(rates[i])) for i in range(lo, hi + 1))


def _rows(inputs: EngineInputs, try_levers: Levers):
    """Each impact row: (spec, child index, the assumed levers with that lever's try value), in LEVERS order."""
    hh = inputs.household
    assumed = clamp(inputs.levers, hh)
    trial = clamp(try_levers, hh)
    for spec in LEVERS:
        for child_index in (range(len(hh.children)) if spec.key == "college" else (None,)):
            if child_index is not None and hh.children[child_index].share_pct == 0:
                continue                               # nothing the lever can change for a kid covered 0%
            yield spec, child_index, with_try(assumed, trial, spec.key, children=hh.children, child_index=child_index)


def _impact(inputs: EngineInputs, spec, child_index, levers: Levers, base_result: SolveResult,
            new_rates: Sequence[tuple[int, float]] | None) -> LeverImpact:
    """new_rates None means the row changes nothing."""
    hh = inputs.household
    child_label = hh.children[child_index].label if child_index is not None else None
    value = try_value(spec, levers, child_index=child_index, children=hh.children)
    if new_rates is None:
        return LeverImpact(spec.key, spec.label, child_label, value, 0, base_result.comfortable_age, "No change")
    delta = delta_months(base_result.success_by_age, new_rates)
    age = first_age(new_rates, COMFORTABLE)
    return LeverImpact(spec.key, spec.label, child_label, value, delta, age, impact_text(delta, base_result.comfortable_age, age))


def _sorted(impacts: list[LeverImpact]) -> tuple[LeverImpact, ...]:
    impacts.sort(key=lambda i: (i.delta_months is None, -abs(i.delta_months or 0), i.comfortable_age is None, i.comfortable_age or 0))
    return tuple(impacts)


def lever_impacts(inputs: EngineInputs, try_levers: Levers, *, base: SolveResult | None = None,
                  prepared: Prepared | None = None) -> tuple[LeverImpact, ...]:
    """The same answers as one windowed solve per lever (_lever_impacts_per_trial), from one batched simulation of
    every lever's window (simulate.trial_success_rates), plus one more batch for each round of widening.

    Columns that can no longer reach the comfortable rate are dropped early; that never changes an answer, since an
    impact reads only which ages reach it and the exact rates at a trial's first crossing and the age before it.
    """
    validate(inputs)
    hh = inputs.household
    assumed = clamp(inputs.levers, hh)
    prep = prepared if prepared is not None else prepare(hh)
    full_ages = candidate_ages(hh)
    base_result = base if base is not None else solve(inputs, assumed, prepared=prep, band=False)

    rows = list(_rows(inputs, try_levers))
    trials: dict[Levers, int] = {}
    for _, _, levers in rows:
        if levers != assumed:
            trials.setdefault(levers, len(trials))
    trial_list = list(trials)
    base_age = base_result.comfortable_age
    # With no interpolated baseline age every delta is None, so only which ages reach the threshold matters and a
    # doomed column can go at once; otherwise the age before a trial's first crossing must keep its exact rate.
    keep_before = fractional_age(base_result.success_by_age, COMFORTABLE) is not None
    rates = np.full((len(trial_list), len(full_ages)), _UNRUN)
    while True:                                  # one batch for every first window, then one per round of widening
        columns = []
        for k in range(len(trial_list)):
            lo, hi, settled = _search(rates[k], base_age, full_ages)
            if not settled:
                columns.extend((i, k) for i in range(lo, hi + 1) if not _known(rates[k], i))
        if not columns:
            break
        got = trial_success_rates(inputs, trial_list, full_ages, prep, columns=columns, stop_below=COMFORTABLE,
                                  keep_before_crossing=keep_before)
        for i, k in columns:
            rates[k, i] = got[k, i]
    impacts = []
    for spec, child_index, levers in rows:
        new_rates = None
        if levers != assumed:
            k = trials[levers]
            lo, hi, _ = _search(rates[k], base_age, full_ages)
            new_rates = _curve(rates[k], full_ages, lo, hi)
        impacts.append(_impact(inputs, spec, child_index, levers, base_result, new_rates))
    return _sorted(impacts)


def _lever_impacts_per_trial(inputs: EngineInputs, try_levers: Levers, *, base: SolveResult | None = None,
                             prepared: Prepared | None = None) -> tuple[LeverImpact, ...]:
    """The reference: one windowed solve per lever. Kept for the test that lever_impacts gives the same answers."""
    hh = inputs.household
    assumed = clamp(inputs.levers, hh)
    prep = prepared if prepared is not None else prepare(hh)
    full_ages = candidate_ages(hh)
    base_result = base if base is not None else solve(inputs, assumed, prepared=prep, band=False)
    impacts = []
    for spec, child_index, levers in _rows(inputs, try_levers):
        new_rates = None
        if levers != assumed:
            new_rates = _solve_near(inputs, levers, base_result.comfortable_age, full_ages, prep).success_by_age
        impacts.append(_impact(inputs, spec, child_index, levers, base_result, new_rates))
    return _sorted(impacts)
