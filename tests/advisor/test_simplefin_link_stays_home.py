"""The SimpleFIN link (SimplefinLink.access_url) is Steward's alone: no advisor, boundary or gateway module reads it,
so no tool result, question or turn can carry it."""
from pathlib import Path

import steward.advisor
import steward_boundary
import steward_gateway

FORBIDDEN = ("SimplefinLink", "simplefin_link", "access_url")


def test_no_advisor_boundary_or_gateway_module_reads_the_simplefin_link():
    roots = [Path(m.__file__).parent for m in (steward.advisor, steward_boundary, steward_gateway)]
    hits = [str(p) for root in roots for p in root.rglob("*.py") if any(w in p.read_text() for w in FORBIDDEN)]
    assert hits == []
