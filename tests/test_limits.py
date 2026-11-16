"""This year's limits come from the same rule tables Next dollar reads (Engineering choice 1). The 2026 figures are
the IRS's (Notice 2025-67, Rev. Proc. 2025-19); a year without its own table is missing, and the CLI says so."""
import re
from datetime import date
from pathlib import Path

import steward
from steward.engine import decisions
from steward.engine.tax import rules
from steward.services import limits as L


def test_the_2026_limits_are_the_irs_figures():
    assert L.have_year(2026)
    assert [L.k401_cents(age, 2026) for age in (44, 50, 62, 64)] == [2_450_000, 3_250_000, 3_575_000, 3_250_000]
    assert [L.ira_cents(age, 2026) for age in (49, 50)] == [750_000, 860_000]
    assert L.hsa_cents(False, (44,), 2026) == 440_000
    assert L.hsa_cents(True, (44, 42), 2026) == 875_000
    assert L.hsa_cents(True, (56, 55), 2026) == 1_075_000


def test_a_year_without_its_own_table_is_missing_and_the_cli_says_so():
    assert not L.have_year(2099)
    assert L.cli_warning(date(2099, 1, 2)) == (
        "Steward has no contribution limits for 2099 yet. Add src/steward/engine/data/rules/retirement_2099.json from "
        "the IRS's published figures; until then the account pages say so.")
    assert L.cli_warning(date(2026, 10, 13)) is None


def test_next_dollar_reads_the_same_limits():
    assert L.hsa_cents(True, (44, 42), 2026) == decisions.hsa_limit(True, (44, 42), 2026)[0]
    assert L.ira_cents(50, 2026) == decisions.roth_ira_limit(0, "mfj", 50, 2026)[0]
    assert L.k401_cents(44, 2026) == rules.table("retirement", 2026)["k401_deferral"] * 100


def test_no_module_repeats_a_limit_figure():
    root = Path(steward.__file__).parent
    figure = re.compile(r"\b(24_?500|2_?450_?000|8_?750|875_?000|4_?400|440_?000)\b")
    assert [str(p.relative_to(root)) for p in root.rglob("*.py") if figure.search(p.read_text())] == []
