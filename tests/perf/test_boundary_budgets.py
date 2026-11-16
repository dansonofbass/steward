"""The boundary's secret rule on the clock. tests/boundary/test_text.py checks its linearity by counting its work, so a
busy machine can't fail a deploy; this times it too, which also sees a regex that backtracks inside one call.
uv run pytest -q -m perf tests/perf/test_boundary_budgets.py"""
import time

import pytest

from steward_boundary.text import secret_edits

pytestmark = pytest.mark.perf


def _took(t: str) -> float:
    start = time.process_time()     # this process's CPU time, not the wall clock
    secret_edits(t)
    return time.process_time() - start


@pytest.mark.parametrize("chunk", ["1 ", "1234 ", "one ", "pin 1 ", "1111 is my pin ", "password is a ", "pin#",
                                   "pin1111/", "code-pin-", "1111#pin "])
def test_the_secret_rule_is_linear_on_long_text(chunk):
    """Four times the text takes about four times as long (a quadratic scan would take sixteen)."""
    short, long = chunk * (2000 // len(chunk)), chunk * (8000 // len(chunk))
    _took(short)
    a, b = min(_took(short) for _ in range(3)), min(_took(long) for _ in range(3))
    assert b < 8 * a + 0.01, (a, b)
