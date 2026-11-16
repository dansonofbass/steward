"""Ruling R2 (spec 2026-11-05, section 7): Steward never calls a household member he, him, his, she or her. The
owner is JR (they/them), and the public app serves anyone. The Plan names its two people by their labels."""
import ast
import re
from dataclasses import replace
from pathlib import Path

from steward.engine.checklist import ChecklistInputs, savings_checklist
from steward.engine.inputs import EngineInputs
from steward.engine.simulate import prepare
from steward.engine.solver import ESTIMATE_LINE, build_assumptions, solve
from steward.engine.synthetic import synthetic_household
from steward.services.plan import checklist_out, people_in, result_out
from steward.services.plan_levers import FIELD_LABELS
from tests.engine.assumption_cases import CASES

PRONOUN = re.compile(r"\b(he|him|his|himself|she|her|hers|herself)\b", re.IGNORECASE)
NAMES = {"jr": "Alex", "spouse": "Sam", "joint": "Joint"}
ROOT = Path(__file__).resolve().parents[1] / "src" / "steward"


def test_no_assumption_line_says_he_or_she():
    for case, (hh, levers) in CASES.items():
        for line in build_assumptions(hh, levers, 2000):
            assert not PRONOUN.search(line), (case, line)


def test_the_plan_names_person_1_by_label():
    inputs = synthetic_household()
    est = replace(inputs.household, jr=replace(inputs.household.jr, estimated=True))
    out = result_out(solve(EngineInputs(est, inputs.levers), prepared=prepare(est, n_hist=50)), NAMES)
    assert ("No earnings record for Alex: their Social Security is estimated from today's salary, as if their pay "
            "had followed the national average wage since 22.") in out["assumptions"]
    assert all("{person" not in t and not PRONOUN.search(t) for t in out["assumptions"])
    assert people_in(ESTIMATE_LINE, NAMES).startswith("No earnings record for Alex: their")


def test_the_checklist_names_person_1_by_label():
    ci = ChecklistInputs(spending_basis_cents=0, cash_cents=0, k401_pct_bp=None, match_cap_bp=None,
                         k401_contribution_cents=None, has_credit_accounts=False, interest_charges_3mo=None,
                         has_hsa=False, hsa_contributions_12mo_cents=None, owners=("Alex", "Sam"),
                         roth_contributed_owners=frozenset(), taxable_contributions_12mo_cents=None)
    rows = checklist_out(savings_checklist(ci), NAMES)
    whys = {r["key"]: r["why"] for r in rows}
    assert whys["full_match"] == "Enter Alex's pay and match to check this."
    assert whys["k401_limit"] == "Enter Alex's pay to check this."


def test_no_string_steward_shows_says_he_or_she():
    """Every string literal under src/steward that isn't a docstring."""
    hits = []
    for path in sorted(ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        hits += [f"{path.relative_to(ROOT)}:{n.lineno}" for n in ast.walk(tree)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
                 and PRONOUN.search(n.value)]
    assert hits == []


def test_the_lever_labels_name_person_1_through_the_slot():
    assert FIELD_LABELS["jr_claim_age"] == "{person1}'s claiming age"
    assert not any("JR" in label for label in FIELD_LABELS.values())
