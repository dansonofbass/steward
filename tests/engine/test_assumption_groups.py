"""How it works' folds (P28, P29): every assumption line keeps its exact words, and carries one of six groups."""
import json
from dataclasses import replace
from pathlib import Path

from steward.engine.inputs import EngineInputs
from steward.engine.simulate import prepare
from steward.engine.solver import (COLLEGE_LINE, D10_LINE, D11_LINE, ESTIMATE_LINE, GROUP_KEYS, build_assumption_lines,
                                   build_assumptions, solve)
from steward.engine.synthetic import synthetic_household
from tests.engine.assumption_cases import CASES

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "assumptions_main.json"


def test_every_string_is_byte_identical_to_main_and_every_line_has_a_group():
    want = json.loads(FIXTURE.read_text())
    assert set(want) == set(CASES)
    for name, (hh, levers) in CASES.items():
        lines = build_assumption_lines(hh, levers, 2000)
        assert [t for t, _ in lines] == want[name], name
        assert build_assumptions(hh, levers, 2000) == tuple(want[name])
        assert {g for _, g in lines} <= set(GROUP_KEYS)


def test_lines_go_to_their_folds():
    groups = dict(build_assumption_lines(*CASES["ny_young_stale"], 2000))
    by_start = {next(t for t in groups if t.startswith(p)): g for p, g in (
        ("Markets:", "markets"), ("Social Security benefits are cut", "ss"), ("Social Security is computed", "ss"),
        ("No earnings record for {person2}", "ss"), ("Survivors keep", "ss"), ("Social Security claimed while", "ss"),
        ("401(k) deferrals", "taxes"), ("Taxes:", "taxes"), ("State tax isn't calculated", "taxes"),
        ("Based on 7 months", "notice"), ("Health insurance before Medicare", "costs"), ("Lifespans come from", "lifespans"),
        ("Retirement spending is met", "costs"), ("A required minimum distribution", "costs"),
        ("Funds on a default mix", "notice"), ("Lifespans use the male", "lifespans"),
        ("The single filing status", "taxes"), ("Taxable's balance was last updated", "notice"))}
    assert all(groups[t] == g for t, g in by_start.items())
    assert (groups[COLLEGE_LINE], groups[D10_LINE], groups[D11_LINE]) == ("costs", "costs", "taxes")
    assert dict(build_assumption_lines(*CASES["no_kids_paid_off"], 2000))[ESTIMATE_LINE] == "ss"


def test_solve_fills_groups_parallel_to_assumptions_and_past_70_is_a_notice():
    inputs = synthetic_household()
    res = solve(inputs, prepared=prepare(inputs.household, n_hist=50))
    assert len(res.assumption_groups) == len(res.assumptions) and set(res.assumption_groups) <= set(GROUP_KEYS)
    old = replace(inputs.household, jr=replace(inputs.household.jr, birth_year=1950))
    res = solve(EngineInputs(old, inputs.levers), prepared=prepare(old, n_hist=50))
    assert (res.assumptions[-1], res.assumption_groups[-1]) == ("{person1} is past 70; no retirement ages were tested.", "notice")
    assert len(res.assumption_groups) == len(res.assumptions)
