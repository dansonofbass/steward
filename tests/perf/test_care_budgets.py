"""Spec 9: one care projection (5 scenarios x 40 years) under 300 ms p95 on the NAS budget factor.
Run: STEWARD_PERF_FACTOR=2.5 uv run pytest -q -m perf tests/perf/test_care_budgets.py -s"""
import os
import time

import pytest

from steward.care import costs as C
from steward.care.book import CareBook, PolicyTerms
from steward.care.scenarios import run
from steward.care.store import Scenario
from steward.engine.project import Assumptions, Income

pytestmark = pytest.mark.perf
FACTOR = float(os.environ.get("STEWARD_PERF_FACTOR", "1"))


def _check(name, value_ms, budget_ms):
    print(f"\nPERF {name}: {value_ms:.2f} ms (budget {budget_ms} ms, factor {FACTOR})")
    assert value_ms * FACTOR < budget_ms, f"{name} {value_ms * FACTOR:.2f} ms exceeds {budget_ms} ms"


def _p95(times):
    return sorted(times)[max(0, int(len(times) * 0.95) - 1)]


BOOK = CareBook(this_year=2026, person_label="Margaret", birth_year=1961, spouse_birth_year=None, state="CA",
                care_inflation=0.04, cash_cents=4_000_000, taxable_cents=15_000_000, traditional_cents=40_000_000,
                roth_cents=5_000_000, home_value_cents=78_000_000,
                incomes=(Income(label="Social Security", amount_cents=2_800_000, start_year=2026, kind="social_security"),
                         Income(label="Pension", amount_cents=1_200_000, start_year=2026, growth="fixed_dollars")),
                spending_yearly_cents=4_000_000, spending_months=12, spending_typed=False,
                policies=(PolicyTerms(1, 15_000, None, 90, None, 3, 0.03),), notes=())
SCENARIOS = (Scenario(1, "at_home"), Scenario(2, "in_home_help", hours_week=20, start_year=2028),
             Scenario(3, "assisted_living", start_year=2030), Scenario(4, "memory_care", start_year=2032),
             Scenario(5, "nursing_home", start_year=2034, sell_home_year=2034, home_basis_cents=9_500_000))


def test_five_scenarios_over_40_years_under_300ms():
    figs = C.figures({}, 2026, 0.04)
    a = Assumptions(care_inflation=0.04)

    def once():
        return [run(BOOK, s, figs, a, years=40) for s in SCENARIOS]

    assert all(len(r.years) == 40 for r in once())
    times = []
    for _ in range(20):
        t0 = time.perf_counter()
        once()
        times.append((time.perf_counter() - t0) * 1000)
    _check("care_projection_5x40", _p95(times), 300)


def test_get_care_on_margarets_book_under_400ms(frozen, margaret, client, mdb):
    from datetime import date

    from steward.demo_parent import seed_parent
    from tests.factories import login
    seed_parent(mdb, date(2026, 10, 13))
    login(client, "jr")
    care = "/api/b/margaret-ellis/care"
    client.put(f"{care}/setup", json={"person": "margaret", "birth_year": 1944, "state": "CA", "care_inflation_bp": 400})
    client.post(f"{care}/scenarios", json={"level": "in_home_help", "hours_week": 20})
    client.post(f"{care}/scenarios", json={"level": "nursing_home", "start_year": 2029, "sell_home_year": 2029})
    assert client.get(care).status_code == 200
    times = []
    for _ in range(20):
        t0 = time.perf_counter()
        client.get(care)
        times.append((time.perf_counter() - t0) * 1000)
    _check("get_care_margaret", _p95(times), 400)
