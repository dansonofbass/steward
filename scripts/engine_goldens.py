"""Regenerate tests/engine/test_golden.py from the engine as it stands.

Run only when a task changes what the plan computes on purpose (a tax rule, D10, D11), and say why with --note; the
note goes in the file's docstring so the history of each regeneration stays readable.

    uv run python scripts/engine_goldens.py --note "Task 7: taxes move to steward.engine.tax (age-65 credits, NIIT)."
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np

from steward.engine.inputs import Levers
from steward.engine.simulate import prepare, simulate
from steward.engine.solver import solve
from steward.engine.synthetic import synthetic_household
from steward.engine.version import ENGINE_VERSION

AGES = [50, 58, 64, 67, 70]
YEARS = [0, 5, 15, 30]
SCENARIOS = (("SYNTHETIC", "Levers()", Levers()),
             ("SPOUSE_CLAIMS_62", "Levers(spouse_claim_age=62)", Levers(spouse_claim_age=62)),
             ("JR_CLAIMS_62", "Levers(jr_claim_age=62)", Levers(jr_claim_age=62)))
TARGET = Path(__file__).resolve().parent.parent / "tests" / "engine" / "test_golden.py"

HEADER = '''"""Golden regression for the plan: synthetic households, 300 histories, default seed. Success rates are exact;
investable percentiles (cents) allow the float32 tolerance used in test_solve.py.

Scenarios: the synthetic household; the spouse claiming Social Security at 62 while JR is still working;
JR claiming at 62 while still working (the claim fork that changes results for the ages that retire later).

Written by scripts/engine_goldens.py; never edit the numbers by hand. Regenerations, newest last:
{notes}
"""
import numpy as np
import pytest

from steward.engine.inputs import Levers
from steward.engine.simulate import prepare, simulate
from steward.engine.solver import solve
from steward.engine.synthetic import synthetic_household

AGES = {ages}
YEARS = {years}
'''

FOOTER = '''

@pytest.mark.parametrize("levers, rates, investable", [
{params}
], ids=["synthetic", "spouse_claims_at_62", "jr_claims_at_62"])
def test_matches_the_golden_values(levers, rates, investable):
    inputs = synthetic_household(levers=levers)
    prep = prepare(inputs.household, n_hist=300)
    assert solve(inputs, prepared=prep, band=False).success_by_age == rates
    out = simulate(inputs, inputs.levers, AGES, prep)
    for (t, age), expected in investable.items():
        got = np.percentile(out.investable[t][:, AGES.index(age)], [10, 50, 90]) * 100
        assert got == pytest.approx(expected, abs=100), (t, age)
'''


FIRST = "- af1e043: values from before the lever trials were batched into one shared working row (fa751ae)."


def _old_notes() -> list[str]:
    m = re.search(r"Regenerations, newest last:\n(.*?)\n\"\"\"", TARGET.read_text(), re.S) if TARGET.exists() else None
    return [line for line in m.group(1).splitlines() if line.strip()] if m else [FIRST]


def render(note: str) -> str:
    notes = _old_notes() + [f"- {note} (engine {ENGINE_VERSION})"]
    out = [HEADER.format(notes="\n".join(notes), ages=AGES, years=YEARS)]
    for name, _, levers in SCENARIOS:
        inputs = synthetic_household(levers=levers)
        prep = prepare(inputs.household, n_hist=300)
        rates = solve(inputs, prepared=prep, band=False).success_by_age
        out.append(f"\n{name}_RATES = (\n" + "".join(f"    ({a}, {r!r}),\n" for a, r in rates) + ")\n")
        sim = simulate(inputs, inputs.levers, AGES, prep)
        rows = []
        for t in YEARS:
            for age in AGES:
                p = np.percentile(sim.investable[t][:, AGES.index(age)], [10, 50, 90]) * 100
                rows.append(f"    ({t}, {age}): ({int(round(p[0]))}, {int(round(p[1]))}, {int(round(p[2]))}),\n")
        out.append(f"{name}_INVESTABLE = {{   # (year offset, retirement age): (p10, p50, p90) in cents\n" + "".join(rows) + "}\n")
    params = "\n".join(f"    ({code}, {name}_RATES, {name}_INVESTABLE)," for name, code, _ in SCENARIOS)
    out.append(FOOTER.format(params=params))
    return "".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--note", required=True, help="why the plan's numbers changed")
    TARGET.write_text(render(ap.parse_args().note))
    print(f"wrote {TARGET}")
