"""Plan subpages: a saved plan's inputs summary holds balances and the big costs' names. It is for the Overview's
line only; nothing on the way to Claude reads it, nor the saved-plan rows that carry it."""
from pathlib import Path

import steward.advisor
import steward_boundary

FORBIDDEN = ("inputs_summary", "plan_out", "plan_history")


def test_no_advisor_or_boundary_module_reads_the_plan_summary():
    roots = [Path(steward.advisor.__file__).parent, Path(steward_boundary.__file__).parent]
    hits = [str(p) for root in roots for p in root.rglob("*.py") if any(w in p.read_text() for w in FORBIDDEN)]
    assert hits == []
