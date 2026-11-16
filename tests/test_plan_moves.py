"""How it works' What moves your plan most (P27, P30): the server sends the numbers, so the Plan chunk needs no
Profile request."""
from dataclasses import replace
from types import SimpleNamespace

from steward import clock
from steward.engine.inputs import Levers
from steward.engine.synthetic import synthetic_household
from steward.services.plan import moves_out
from steward.services.profile_benefits import benefits_out
from tests.factories import make_ready_household, make_user

BENEFITS = {"jr": {"at_67_cents": 335_400}, "spouse": {"at_67_cents": 167_700}}


def test_moves_read_the_plan_inputs_at_the_assumed_levers():
    hh = synthetic_household().household
    assert moves_out(SimpleNamespace(household=hh), Levers(spending_pct=90), BENEFITS) == {
        "ss_at_67": {"jr_cents": 335_400, "spouse_cents": 167_700}, "retirement_spending_cents": 630_000,
        "mortgage_payoff_year": 2048, "health_premium_cents": 2_400_000,
        "college": {"count": 3, "level": "in_state_public"}, "saving_cents": 150_000}


def test_a_paid_off_mortgage_is_left_out_and_mixed_levels_name_no_level():
    hh = synthetic_household().household
    kids = (replace(hh.children[0], cost_level="private"), *hh.children[1:])
    m = moves_out(SimpleNamespace(household=replace(hh, mortgage_payoff_year=2020, children=kids)), Levers(), BENEFITS)
    assert (m["mortgage_payoff_year"], m["college"]) == (None, {"count": 3, "level": None})
    m = moves_out(SimpleNamespace(household=replace(hh, children=())), Levers(), {"jr": {"at_67_cents": None}, "spouse": {"at_67_cents": None}})
    assert (m["college"], m["ss_at_67"]) == ({"count": 0, "level": None}, {"jr_cents": None, "spouse_cents": None})


def test_get_plan_sends_moves_and_the_groups(frozen, signed_in, db):
    make_user(db, "sam", "sam@x.com", "Sam")
    make_ready_household(db)
    body = signed_in.get("/api/b/ours/plan").json()
    jr = benefits_out(db, clock.today())["jr"]["at_67_cents"]
    assert jr and body["inputs"]["moves"] == {
        "ss_at_67": {"jr_cents": jr, "spouse_cents": None}, "retirement_spending_cents": 600_000,
        "mortgage_payoff_year": 2048, "health_premium_cents": 2_400_000,
        "college": {"count": 1, "level": "in_state_public"}, "saving_cents": 200_000}
    assert len(body["result"]["assumption_groups"]) == len(body["result"]["assumptions"])
