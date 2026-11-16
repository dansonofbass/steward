"""The Business page's request (business plan budgets): under 150 ms p95 on the 15,000-row demo vault."""
import os
import time

import pytest

pytestmark = pytest.mark.perf
FACTOR = float(os.environ.get("STEWARD_PERF_FACTOR", "1"))


def _check(name, value_ms, budget_ms):
    print(f"\nPERF {name}: p95={value_ms:.1f} ms (budget {budget_ms} ms, factor {FACTOR})")
    assert value_ms < budget_ms, f"{name} p95 {value_ms:.1f} ms exceeds {budget_ms} ms"


def test_business_report_under_150ms(big_client):
    times = []
    for _ in range(20):
        t0 = time.perf_counter()
        r = big_client.get("/api/b/ours/business")
        times.append((time.perf_counter() - t0) * 1000)
        assert r.status_code == 200
    times.sort()
    _check("business_report", times[int(0.95 * 19)] * FACTOR, 150)
