"""The personal-string scanner on long runs (tests/personal_strings.py): a 300,000-character run, the size of the one in
OpenBLAS that held an image scan for 47 minutes when dotted names were found in square time, read well under a second."""
import os
import time

import pytest

from tests.personal_strings import made_up

pytestmark = pytest.mark.perf
FACTOR = float(os.environ.get("STEWARD_PERF_FACTOR", "1"))
BUDGET_MS = 500


@pytest.mark.parametrize("run", ["x" * 300_000, "ab-" * 100_000, "x" * 299_998 + "-.y", "-" * 300_000])
def test_a_300k_run_is_scanned_well_under_a_second(run):
    m = made_up(glued=("zorblax", 7), whole=("quux", None), host=("y.example", None))
    start = time.process_time()
    assert not m(run)
    ms = (time.process_time() - start) * 1000
    print(f"\nPERF scanner {run[:3]!r}x{len(run)}: {ms:.1f} ms (budget {BUDGET_MS} ms, factor {FACTOR})")
    assert ms < BUDGET_MS * FACTOR
