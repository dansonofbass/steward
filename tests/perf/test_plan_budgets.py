"""Plan API budgets (spec 10) against the seeded 5-year demo households."""
import os
import random
import time
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.perf

# STEWARD_PERF_FACTOR=2.5 on a dev box approximates the DS920+ (J4125), as in test_budgets.py.
FACTOR = float(os.environ.get("STEWARD_PERF_FACTOR", "1"))
DEMO_NOW = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)   # the day after the demo data ends
# A run-unique offset, so a run against a long-lived server (STEWARD_PERF_BASE_URL) never times result-cache hits
# left by an earlier run. On the $50 grid; with the drag values below it stays inside $0-$3,000 a month.
OFF = random.randrange(1, 41) * 5_000
# The offset alone leaves few keys (61 save-more steps x 5 spending steps), which a long-lived server's 256-entry
# cache fills after a dozen runs, so each run also draws its own claiming ages (81 pairs).
CLAIM = {"jr_claim_age": random.randrange(62, 71), "spouse_claim_age": random.randrange(62, 71)}


def _p95_ms(calls):
    times = []
    for call in calls:
        t0 = time.perf_counter()
        r = call()
        times.append((time.perf_counter() - t0) * 1000)
        assert r.status_code == 200, r.text
    times.sort()
    return times[int(0.95 * (len(times) - 1))] * FACTOR


def _check(name, ms, budget):
    print(f"\nPERF {name}: p95={ms:.1f} ms (budget {budget} ms, factor {FACTOR})")
    assert ms < budget, f"{name} p95 {ms:.1f} ms exceeds {budget} ms"


@pytest.fixture
def plan_client(big_client, monkeypatch):
    if not os.environ.get("STEWARD_PERF_BASE_URL"):
        monkeypatch.setattr("steward.clock.now", lambda: DEMO_NOW)
    if "setup" in big_client.get("/api/b/ours/plan").json():
        pytest.skip("this vault's plan isn't set up (seed it with the M2-B demo)")
    return big_client


def _drag_calls(client, off):
    return [lambda v=v: client.post("/api/b/ours/plan/preview", json={"assumed": {
                "save_more_monthly_cents": v + off, "spending_pct": random.choice(range(90, 111)), **CLAIM}})
            for v in range(5_000, 105_000, 5_000)]           # 20 new values: 20 result-cache misses


def _impact_calls(client, off):
    return [lambda v=v: client.post("/api/b/ours/plan/impacts", json={"assumed": {"save_more_monthly_cents": off, "spending_pct": v, **CLAIM}})
            for v in (95, 105, 110)]


def _misses(client) -> int | None:
    """Result-cache misses so far, on the local fixture only (a remote server's cache can't be read)."""
    return None if os.environ.get("STEWARD_PERF_BASE_URL") else client.app.state.books.plan_cache(client.app.state.books.book("ours").id).results.misses


def test_lever_drag_round_trip_under_500ms(plan_client):
    before = _misses(plan_client)
    _check("plan_preview", _p95_ms(_drag_calls(plan_client, OFF)), 500)
    if before is not None:
        assert _misses(plan_client) - before == 20, "the drag must time cache misses, not hits"


def test_lever_impacts_under_3s(plan_client):
    before = _misses(plan_client)
    _check("plan_impacts (median of 3)", _p95_ms(_impact_calls(plan_client, OFF)), 3_000)
    if before is not None:
        assert _misses(plan_client) - before >= 3, "the impacts must time cache misses, not hits"


def test_cashflow_12_months_under_150ms(plan_client):
    _check("cashflow_12m", _p95_ms([lambda: plan_client.get("/api/b/ours/cashflow?months=12")] * 20), 150)


def test_homes_strip_12_months_under_150ms(plan_client):
    _check("spending_flow_12m", _p95_ms([lambda: plan_client.get("/api/b/ours/spending/flow?months=12")] * 20), 150)
