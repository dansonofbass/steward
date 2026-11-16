"""Household tools on the demo household: the plan's numbers match Steward's own Plan service (spec 1)."""
import json
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.orm import Session

from steward.demo import seed, seed_people
from steward.engine import EngineInputs
from steward.services.plan import solve_cached
from steward.services.plan_cache import PlanCache
from steward.services.plan_inputs import build_inputs
from steward.services.plan_levers import resolve_state
from steward_boundary import tools as T
from tests.advisor.helpers import call

TODAY = date(2026, 10, 13)


@pytest.fixture
def household(books, ours, engine):
    with Session(engine) as db:
        seed(db, years=2, seed=7)
    with Session(books.directory) as ddb:
        seed_people(ddb, ours.id)
    people = books.people(ours.id)
    return engine, ours, people, next(p.id for p in people if p.username == "alex"), PlanCache()


def run(h, name, input):
    engine, book, people, jr, cache = h
    out = call(engine, book, people, jr, name, input, TODAY, cache)
    assert out["error"] is None, out
    return out["content"]


def test_facts_send_ages_not_birth_dates(household):
    out = run(household, "facts", {})
    assert out["salary_person"] == "Person 1" and out["salary_cents"] == 16_500_000
    assert out["ages"] == [{"alias": "Person 1", "age": 41}, {"alias": "Person 2", "age": 39}]
    assert out["mortgage_payoff_month"] == "2051-03" and out["mortgage_rate_bp"] == 312.0
    assert "1985" not in json.dumps(out)


def test_plan_result_matches_the_plan_service(household, engine):
    out = run(household, "plan_result", {})
    with Session(engine) as db:
        pi = build_inputs(db, TODAY)
        state, _ = resolve_state({}, None, pi.household, pi.observed)
        res = solve_cached(PlanCache(), EngineInputs(pi.household, state.assumed))
    assert (out["comfortable_age"], out["likely_age"]) == (res.comfortable_age, res.likely_age)
    assert out["age_of"] == "Person 1" and out["saved"] is False
    assert out["assumptions"]["state_tax"] == "california" and out["assumptions"]["histories"] == res.histories
    assert "Alex" not in json.dumps(out) and "jr_" not in json.dumps(out)


def test_what_if_changes_levers_and_saves_nothing(household):
    base = run(household, "plan_result", {})
    out = run(household, "plan_what_if", {"levers": {"save_more_monthly_cents": 50_000, "person_1_claim_age": 70}})
    assert out["levers_used"]["save_more_monthly_cents"] == 50_000 and out["levers_used"]["person_1_claim_age"] == 70
    assert out["comfortable_age"] is None or base["comfortable_age"] is None or out["comfortable_age"] <= base["comfortable_age"]
    assert run(household, "plan_result", {})["saved"] is False


def test_what_if_levers_left_out_or_null_stay_as_they_are(household):
    base = run(household, "plan_result", {})
    unchanged = run(household, "plan_what_if", {"levers": {}})
    assert unchanged["comfortable_age"] == base["comfortable_age"] and unchanged["likely_age"] == base["likely_age"]
    nulls = {f: None for f in (*T.WHAT_IF_INTS, "college_levels", "full_ss_benefits")}
    left_out = run(household, "plan_what_if", {"levers": {"spending_pct": 90}})
    assert run(household, "plan_what_if", {"levers": {**nulls, "spending_pct": 90}}) == left_out
    assert left_out["levers_used"]["spending_pct"] == 90


def test_lever_impacts_use_keys_and_child_aliases(household):
    out = run(household, "plan_lever_impacts", {})
    assert out["impacts"]
    keys = {i["lever"] for i in out["impacts"]}
    assert keys <= {"save_more", "spending", "consulting", "gift", "person_2_earnings", "person_1_claim",
                    "person_2_claim", "college", "full_ss"}
    assert all(i["child"] is None or i["child"].startswith("Child ") for i in out["impacts"])


def test_savings_checklist_sends_keys_statuses_and_numbers(household):
    out = run(household, "savings_checklist", {})
    assert [i["item"] for i in out["items"]][0] == "emergency_fund"
    assert out["numbers"]["k401_pct_bp"] == 800 and out["numbers"]["match_cap_bp"] == 600
    assert all(a in ("Person 1", "Person 2") for a in out["numbers"]["missing_roth"])


def test_a_household_without_facts_says_the_plan_isnt_set_up(books, ours, engine):
    people = books.people(ours.id)
    assert call(engine, ours, people, 1, "plan_result", {}, TODAY)["error"] == "The plan isn't set up yet."


def test_free_text_in_a_result_goes_through_the_stored_text_path(household, monkeypatch):
    """Bank and inventory text is strict: no keep-list, so a symbol that carries a long number is refused."""
    from steward.advisor import tools

    def fake(symbol):
        return lambda inp, env: {"holdings": [{"symbol": symbol, "asset_class": "other", "account": "Account 1",
                                               "value_cents": 1, "cost_basis_cents": None, "as_of": "2026-10-13"}],
                                 "totals_by_asset_class": []}
    engine, book, people, jr, cache = household
    monkeypatch.setitem(tools.REGISTRY, "holdings", fake("12345678"))
    out = call(engine, book, people, jr, "holdings", {}, TODAY, cache)
    assert out["content"] is None and out["error"] == tools.LOOKUP_FAILED
    monkeypatch.setitem(tools.REGISTRY, "holdings", fake("VTI"))
    assert call(engine, book, people, jr, "holdings", {}, TODAY, cache)["error"] is None


def test_plan_result_ages_match_the_plan_screen_when_a_plan_is_saved(household):
    from steward.services.plan import latest_plan, result_out, save_plan
    from steward.services.plan_levers import LeverState
    from steward.engine import Levers
    engine, book, people, jr, cache = household
    with Session(engine) as db:
        pi = build_inputs(db, TODAY)
        state, _ = resolve_state({"assumed": {"spending_pct": 95}}, None, pi.household, pi.observed)
        res = solve_cached(PlanCache(), EngineInputs(pi.household, state.assumed))
        save_plan(db, jr, state, res, datetime(2026, 10, 13, 19, tzinfo=timezone.utc))
        db.commit()
    with Session(engine) as db:
        row = latest_plan(db)
        screen = (row.comfortable_age, row.likely_age)
        pi = build_inputs(db, TODAY)
        from steward.services.plan import saved_state
        again, _ = resolve_state({}, saved_state(row), pi.household, pi.observed)
        shown = result_out(solve_cached(PlanCache(), EngineInputs(pi.household, again.assumed)), pi.names)
    out = run(household, "plan_result", {})
    assert out["saved"] is True
    assert (out["comfortable_age"], out["likely_age"]) == screen == (shown["comfortable_age"], shown["likely_age"])



def test_state_tax_word_comes_from_the_registry():
    from steward.advisor.tools.household import state_tax_word
    from steward_boundary.vocab import STATE_TAX
    assert [state_tax_word(s) for s in ("CA", "TX", "WA", "NY")] == ["california", "none", "none", "not_calculated"]
    assert set(STATE_TAX) == {"california", "none", "not_calculated"}


def test_facts_read_the_mortgage_accounts_rate_first(household):
    """Final review minor a: the rate entered on the Plan screen lives on the account; the chat reads it too."""
    from sqlalchemy import select
    from steward.db.models import Account, AccountType
    engine = household[0]
    with Session(engine) as db:
        db.scalars(select(Account).where(Account.type == AccountType.mortgage)).first().rate_bp = 650
        db.commit()
    assert run(household, "facts", {})["mortgage_rate_bp"] == 650.0
