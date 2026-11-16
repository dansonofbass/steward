"""Next dollar budgets (cash-flow and tax part 4): the ordering under 100 ms p95 at the NAS factor, pure and through
the API. STEWARD_PERF_FACTOR=2.5 on a dev box approximates the DS920+ (J4125)."""
import os
import time
from datetime import datetime, timezone

import pytest

from steward.engine.next_dollar import next_dollar
from tests.engine.test_next_dollar import business, inputs

pytestmark = pytest.mark.perf
FACTOR = float(os.environ.get("STEWARD_PERF_FACTOR", "1"))


def _check(name, value_ms, budget_ms):
    print(f"\nPERF {name}: p95={value_ms:.1f} ms (budget {budget_ms} ms, factor {FACTOR})")
    assert value_ms < budget_ms, f"{name} p95 {value_ms:.1f} ms exceeds {budget_ms} ms"


def _p95(fn, n=30):
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    return times[int(0.95 * (n - 1))] * FACTOR


def test_the_ordering_under_100ms():
    _check("next_dollar_household", _p95(lambda: next_dollar(inputs())), 100)
    _check("next_dollar_business", _p95(lambda: next_dollar(business())), 100)


DEMO_NOW = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)   # the day after the demo data ends


@pytest.fixture
def plan_client(big_client, monkeypatch):
    if not os.environ.get("STEWARD_PERF_BASE_URL"):
        monkeypatch.setattr("steward.clock.now", lambda: DEMO_NOW)
    if "setup" in big_client.get("/api/b/ours/plan").json():
        pytest.skip("this vault's plan isn't set up (seed it with the M2-B demo)")
    return big_client


def test_the_next_dollar_request_under_100ms(plan_client):
    def call():
        r = plan_client.get("/api/b/ours/next-dollar")
        assert r.status_code == 200, r.text
    call()                                               # the plan's inputs cache is warm, as on the Plan screen
    _check("next_dollar_api", _p95(call, 20), 100)
