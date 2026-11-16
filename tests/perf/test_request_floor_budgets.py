"""Phase 18 (docs/perf/2026-11-01-phase18-measurement.md, Budgets): a signed-in GET's floor above /api/health. Timing
lives only here, never in a deploy gate (JR's rule). Run with:
uv run pytest -q -m perf tests/perf/test_request_floor_budgets.py (STEWARD_PERF_FACTOR=2.5 on a dev box approximates
the NAS). The NAS's own number comes from the phone run and the desktop probe in docs/perf."""
import os
import statistics
import time

import pytest

pytestmark = pytest.mark.perf
FACTOR = float(os.environ.get("STEWARD_PERF_FACTOR", "1"))
FLOOR_MS = 20


def _median_ms(fn, n=100):
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        r = fn()
        times.append((time.perf_counter() - t0) * 1000)
        assert r.status_code == 200
    return statistics.median(times)


def test_the_signed_in_floor_is_within_20ms_of_health(signed_in):
    for _ in range(10):
        signed_in.get("/api/b/ours/accounts")            # warm the pools
    signed = _median_ms(lambda: signed_in.get("/api/b/ours/accounts"))
    health = _median_ms(lambda: signed_in.get("/api/health"))
    floor = signed - health
    print(f"\nPERF signed-in floor: {floor:.2f} ms (budget {FLOOR_MS * FACTOR} ms, factor {FACTOR})")
    assert floor < FLOOR_MS * FACTOR
