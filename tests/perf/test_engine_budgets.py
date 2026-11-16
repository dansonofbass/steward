import os
import time
from dataclasses import replace

import pytest

from steward.engine.impacts import lever_impacts
from steward.engine.levers import ObservedTry, default_try
from steward.engine.simulate import prepare
from steward.engine.solver import solve
from steward.engine.synthetic import synthetic_household

pytestmark = pytest.mark.perf

# Spec section 10: full solve < 400 ms and lever impacts < 3 s on the NAS (Celeron J4125).
# Set STEWARD_PERF_FACTOR=2.5 on a dev box: a J4125 core is about 2.5x slower than a fast desktop core (README),
# so the dev-box targets are effectively 160 ms and 1.2 s.
FACTOR = float(os.environ.get("STEWARD_PERF_FACTOR", "1"))


def _median_ms(fn, n):
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    return times[len(times) // 2] * FACTOR


def test_full_solve_under_400ms():
    inputs = synthetic_household()
    solve(inputs)                                       # warm-up: data files load and caches fill
    ms = _median_ms(lambda: solve(inputs), 5)
    print(f"\nPERF engine_solve: median={ms:.1f} ms (budget 400 ms, factor {FACTOR})")
    assert ms < 400, f"engine solve {ms:.1f} ms exceeds 400 ms"


def test_lever_impacts_under_3s():
    inputs = synthetic_household()
    prep = prepare(inputs.household)
    base = solve(inputs, prepared=prep)
    trial, _ = default_try(inputs.household, inputs.levers, ObservedTry(consulting_12mo_cents=600_000, gift_12mo_cents=1_000_000, spouse_earnings_cents=6_000_000))
    lever_impacts(inputs, trial, base=base, prepared=prep)   # warm-up
    ms = _median_ms(lambda: lever_impacts(inputs, trial, base=base, prepared=prep), 3)
    print(f"\nPERF engine_impacts: median={ms:.1f} ms (budget 3000 ms, factor {FACTOR})")
    assert ms < 3000, f"lever impacts {ms:.1f} ms exceeds 3000 ms"


def test_lever_impacts_under_3s_when_not_comfortable_by_70():
    # Worst case for the impacts: no windowed search, so every lever solves across the full age range.
    inputs = synthetic_household(spending_basis_cents=22_000_000)
    prep = prepare(inputs.household)
    base = solve(inputs, prepared=prep)
    assert base.comfortable_age is None
    trial, _ = default_try(inputs.household, inputs.levers, ObservedTry(consulting_12mo_cents=600_000, gift_12mo_cents=1_000_000, spouse_earnings_cents=6_000_000))
    trial = replace(trial, college_levels=("private",) * 3)
    lever_impacts(inputs, trial, base=base, prepared=prep)   # warm-up
    ms = _median_ms(lambda: lever_impacts(inputs, trial, base=base, prepared=prep), 3)
    print(f"\nPERF engine_impacts_worst: median={ms:.1f} ms (budget 3000 ms, factor {FACTOR})")
    assert ms < 3000, f"lever impacts (not comfortable by 70) {ms:.1f} ms exceeds 3000 ms"


def _p95_ms(fn, n):
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    return times[int(0.95 * (n - 1))] * FACTOR


def test_annual_tax_under_2ms():
    # Spec 9: annual_tax under 2 ms. The demo household with a business, dividends, three children and California.
    from steward.engine.tax import TaxFacts, annual_tax
    facts = TaxFacts(filing="mfj", ages=(44, 42), state="CA", business_profit_cents=9_000_000, business_sstb=True,
                     interest_cents=40_000, ordinary_dividends_cents=120_000, qualified_dividends_cents=100_000,
                     hsa_contributions_cents=500_000, se_health_insurance_cents=1_200_000, mortgage_interest_cents=1_400_000,
                     property_tax_cents=900_000, state_income_tax_cents=300_000, charity_cents=200_000, dependents=(11, 8, 5))
    annual_tax(facts, 2026)
    ms = _p95_ms(lambda: annual_tax(facts, 2026), 300)
    print(f"\nPERF annual_tax: p95={ms:.3f} ms (budget 2 ms, factor {FACTOR})")
    assert ms < 2, f"annual_tax {ms:.3f} ms exceeds 2 ms"


def test_one_40_year_projection_under_60ms():
    # Spec 9 budgets a care projection (5 scenarios x 40 years) at 300 ms p95; one scenario gets a fifth of it.
    from steward.engine.project import Assumptions, Expense, Income, LtcPolicy, ProjectionInputs, project
    p = ProjectionInputs(start_year=2026, filing="single", state="CA", birth_years=(1944,), cash_cents=4_000_000,
                         taxable_cents=15_000_000, traditional_cents=40_000_000, roth_cents=5_000_000,
                         incomes=(Income("Social Security", 2_800_000, 2026, kind="social_security"),
                                  Income("Pension", 1_200_000, 2026, kind="pension")),
                         expenses=(Expense("Spending", 4_000_000, 2026),
                                   Expense("Assisted living", 8_400_000, 2028, kind="care", medical=True, growth="care")),
                         ltc_policies=(LtcPolicy(2028, benefit_daily_cents=15_000, waiting_days=90, benefit_years=3),))
    project(p, Assumptions(), 40)
    ms = _p95_ms(lambda: project(p, Assumptions(), 40), 40)
    print(f"\nPERF project_40y: p95={ms:.1f} ms (budget 60 ms, factor {FACTOR})")
    assert ms < 60, f"a 40-year projection {ms:.1f} ms exceeds 60 ms"
