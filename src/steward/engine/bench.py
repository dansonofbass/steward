"""Timing harness behind `steward bench` (spec section 10): the solve and the impacts on real hardware."""
from __future__ import annotations

import platform
import statistics
import time
from dataclasses import dataclass, replace
from pathlib import Path

from steward.engine.impacts import lever_impacts
from steward.engine.levers import ObservedTry, default_try
from steward.engine.market import N_HISTORIES
from steward.engine.simulate import prepare
from steward.engine.solver import candidate_ages, solve
from steward.engine.synthetic import synthetic_household


@dataclass(frozen=True)
class BenchResult:
    cpu: str
    histories: int
    ages: int
    solve_ms: tuple[float, ...]
    impacts_ms: float
    impacts_worst_ms: float       # not comfortable by 70: every lever solves across the full age range
    solve_budget_ms: float = 400.0
    impacts_budget_ms: float = 3000.0

    @property
    def solve_median_ms(self) -> float:
        return statistics.median(self.solve_ms)

    @property
    def within_budget(self) -> bool:
        return (self.solve_median_ms < self.solve_budget_ms and self.impacts_ms < self.impacts_budget_ms
                and self.impacts_worst_ms < self.impacts_budget_ms)


def _cpu_name() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine() or "unknown CPU"


def _timed(fn) -> float:
    t0 = time.perf_counter()
    fn()
    return (time.perf_counter() - t0) * 1000


def run_bench(runs: int = 5, histories: int = N_HISTORIES) -> BenchResult:
    inputs = synthetic_household()
    hh = inputs.household
    solve(inputs, prepared=prepare(hh, n_hist=histories))                      # warm-up
    solve_ms = tuple(_timed(lambda: solve(inputs, prepared=prepare(hh, n_hist=histories))) for _ in range(runs))
    prep = prepare(hh, n_hist=histories)
    base = solve(inputs, prepared=prep)
    observed = ObservedTry(consulting_12mo_cents=600_000, gift_12mo_cents=1_000_000, spouse_earnings_cents=6_000_000)
    trial, _ = default_try(hh, inputs.levers, observed)
    impacts_ms = _timed(lambda: lever_impacts(inputs, trial, base=base, prepared=prep))
    # The worst case, as tests/perf/test_engine_budgets.py times it: not comfortable by 70, every row a real change.
    worst = synthetic_household(spending_basis_cents=22_000_000)
    worst_prep = prepare(worst.household, n_hist=histories)
    worst_base = solve(worst, prepared=worst_prep, band=False)
    worst_trial, _ = default_try(worst.household, worst.levers, observed)
    worst_trial = replace(worst_trial, college_levels=("private",) * len(worst.household.children))
    impacts_worst_ms = _timed(lambda: lever_impacts(worst, worst_trial, base=worst_base, prepared=worst_prep))
    return BenchResult(cpu=_cpu_name(), histories=histories, ages=len(candidate_ages(hh)), solve_ms=solve_ms,
                       impacts_ms=impacts_ms, impacts_worst_ms=impacts_worst_ms)


def format_bench(r: BenchResult) -> str:
    solve_flag = "" if r.solve_median_ms < r.solve_budget_ms else "  OVER BUDGET"
    impacts_flag = "" if r.impacts_ms < r.impacts_budget_ms else "  OVER BUDGET"
    worst_flag = "" if r.impacts_worst_ms < r.impacts_budget_ms else "  OVER BUDGET"
    return "\n".join([
        f"steward bench — retirement engine on {r.cpu}",
        f"solve ({r.histories:,} histories x {r.ages} ages, including the random draws): "
        f"median {r.solve_median_ms:.0f} ms over {len(r.solve_ms)} runs (budget {r.solve_budget_ms:.0f} ms){solve_flag}",
        f"lever impacts (same histories): {r.impacts_ms:.0f} ms (budget {r.impacts_budget_ms:.0f} ms){impacts_flag}",
        f"Lever impacts, worst case (not comfortable by 70): {r.impacts_worst_ms:.0f} ms (budget {r.impacts_budget_ms:.0f} ms){worst_flag}",
    ])
