"""Roth or traditional (spec 7.3; rulings 15-18). Fictional household (tests/factories.make_ready_household)."""
from dataclasses import replace
from datetime import date

from steward.engine import Levers
from steward.engine.inputs import InputError
from steward.services.plan_inputs import build_inputs
from steward.taxes import roth
from steward.taxes.roth import FINISH_PLAN, LaterRate, later_rate, roth_out, roth_view
from tests.factories import add_fact, login, make_ready_household, make_user
from tests.taxes.helpers import household

TODAY = date(2026, 10, 13)


def test_the_rate_later_comes_from_a_projection_with_rmds(db):
    make_ready_household(db)
    pi = build_inputs(db, TODAY)
    lr = later_rate(pi, Levers(), 65, "65 until a plan is saved")
    assert (lr.retire_age, lr.retire_year, lr.from_year, lr.to_year) == (65, 2047, 2057, 2066)   # born 1982: RMDs at 75
    assert 0.0 < lr.rate < 0.5
    assert lr.line == "From retiring at 65 (65 until a plan is saved), with required withdrawals from 2057 and Social Security."
    bigger = replace(pi, household=replace(pi.household, traditional=replace(pi.household.traditional,
                                                                             balance_cents=pi.household.traditional.balance_cents * 10)))
    assert later_rate(bigger, Levers(), 65, "x").rate >= lr.rate


def test_the_view_compares_this_year_with_later(db):
    make_ready_household(db)
    v = roth_view(db, TODAY)
    assert v.later is not None and v.later_reason is None and v.rate_later == v.later.rate
    assert 0.25 <= v.rate_now <= 0.40                            # a $160,000 salary in California
    assert v.line.startswith(("Roth this year:", "Traditional this year:", "About the same:"))
    assert v.lean in ("roth", "traditional", "either")
    out = roth_out(v)
    assert out["available"] is True and out["later_line"] == v.later.line and out["never"] == "Steward never pays or files anything."
    assert out["rules_note"] == "2026 federal and 2025 California rules"


def test_without_plan_setup_there_is_no_later_rate(db):
    household(db, salary="16500000")
    v = roth_view(db, TODAY)
    assert (v.later, v.later_reason, v.lean, v.conversion) == (None, FINISH_PLAN, "either", None)
    assert v.line.startswith("Traditional saves about ") and v.line.endswith("there's no retirement estimate to compare with yet.")
    assert roth_out(v)["later_line"] == FINISH_PLAN


def test_a_low_income_year_offers_a_conversion(db, monkeypatch):
    make_ready_household(db)
    add_fact(db, "jr.salary_cents", "3000000", as_of=date(2026, 10, 2))        # this year's pay fell to $30,000
    monkeypatch.setattr(roth, "later_rate", lambda *a, **k: LaterRate(0.24, 65, 2047, 2057, 2066, "From retiring at 65."))
    v = roth_view(db, TODAY)
    assert v.lean == "roth"
    assert v.conversion is not None and v.conversion.line.startswith("This year's rate is low: converting $")
    assert roth_out(v)["conversion"]["amount_cents"] == v.conversion.amount_cents


def test_next_dollar_uses_the_projections_rate(db):
    from steward.services.next_dollar import build_next_dollar
    make_ready_household(db)
    nd = build_next_dollar(db, TODAY, build_inputs(db, TODAY))
    assert nd.later_rate is not None and nd.later_rate == roth_view(db, TODAY).rate_later


def test_the_route(frozen, signed_in, db):
    make_ready_household(db)
    r = signed_in.get("/api/b/ours/taxes/roth").json()
    assert r["available"] is True and r["lean"] in ("roth", "traditional", "either") and isinstance(r["rate_now"], float)


def test_an_engine_refusal_names_person_1_by_label(frozen, client, db, monkeypatch):
    """TRI-1: an engine refusal that reaches Taxes as the reason names Person 1 by the household's label."""
    def refuse(*args, **kwargs):
        raise InputError("{person1} must be born before the plan year.")
    make_user(db, username="alex", email="alex@x.com", display_name="Alex")
    login(client, "alex")
    monkeypatch.setattr("steward.api.taxes.roth_view", refuse)
    r = client.get("/api/b/ours/taxes/roth").json()
    assert r == {"available": False, "reason": "Alex must be born before the plan year."}


def test_parent_books_have_no_roth(frozen, client, margaret):
    login(client, "jr")
    assert client.get("/api/b/margaret-ellis/taxes/roth").status_code == 404
