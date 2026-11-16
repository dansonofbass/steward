"""Taxes budgets (plan Global Constraints), p95 on the NAS factor against the 15,000-row demo vault (big_client in
tests/perf/conftest.py): GET /taxes/quarterly < 150 ms, /taxes/notice < 100 ms; Tasks 7 and 8 add /taxes/plans,
/taxes/roth and the rate-later projection.
Run: STEWARD_PERF_FACTOR=2.5 uv run pytest -q -m perf tests/perf/test_tax_budgets.py -s"""
import os
import time

import pytest

pytestmark = pytest.mark.perf
FACTOR = float(os.environ.get("STEWARD_PERF_FACTOR", "1"))


def _check(name, value_ms, budget_ms):
    print(f"\nPERF {name}: {value_ms:.2f} ms (budget {budget_ms} ms, factor {FACTOR})")
    assert value_ms * FACTOR < budget_ms, f"{name} {value_ms * FACTOR:.2f} ms exceeds {budget_ms} ms"


def _p95(times):
    return sorted(times)[max(0, int(len(times) * 0.95) - 1)]


def _time(client, url, n=20):
    r = client.get(url)
    assert r.status_code == 200
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        client.get(url)
        times.append((time.perf_counter() - t0) * 1000)
    return _p95(times)


def test_quarterly_under_150ms(big_client):
    assert big_client.get("/api/b/ours/taxes/quarterly").json()["available"] is True
    _check("taxes_quarterly", _time(big_client, "/api/b/ours/taxes/quarterly"), 150)


def test_notice_under_100ms(big_client):
    _check("taxes_notice", _time(big_client, "/api/b/ours/taxes/notice"), 100)


def test_plans_under_200ms(big_client):
    assert big_client.get("/api/b/ours/taxes/plans").json()["available"] is True
    _check("taxes_plans", _time(big_client, "/api/b/ours/taxes/plans"), 200)


def test_rate_later_projection_under_200ms(frozen, db):
    from datetime import date

    from steward.engine import Levers
    from steward.services.plan_inputs import build_inputs
    from steward.taxes.roth import later_rate
    from tests.factories import make_ready_household
    make_ready_household(db)
    pi = build_inputs(db, date(2026, 10, 13))
    times = []
    for _ in range(20):
        t0 = time.perf_counter()
        later_rate(pi, Levers(), 65, "x")
        times.append((time.perf_counter() - t0) * 1000)
    _check("taxes_rate_later", _p95(times), 200)


def test_roth_under_300ms(big_client):
    assert big_client.get("/api/b/ours/taxes/roth").json()["available"] is True
    _check("taxes_roth", _time(big_client, "/api/b/ours/taxes/roth"), 300)
