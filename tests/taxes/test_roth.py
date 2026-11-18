"""Roth or traditional (spec 7.3; rulings 15-18). Fictional household (tests/factories.make_ready_household)."""
from dataclasses import replace
from datetime import date, datetime, timezone

from steward.db.models import Plan
from steward.engine import Levers
from steward.engine.version import ENGINE_VERSION
from steward.engine.inputs import InputError
from steward.services import next_dollar
from steward.services.plan_inputs import build_inputs
from steward.taxes import roth
from steward.taxes.roth import FINISH_PLAN, LaterRate, later_rate, roth_out, roth_view, saved_plan_later_rate
from tests.factories import add_fact, login, make_ready_household, make_user
from tests.taxes.helpers import household

TODAY = date(2026, 10, 13)
LEVERS = '{"assumed": {}, "try": {}, "pinned": []}'


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


def test_the_later_line_names_which_saved_age_and_when_it_was_saved(db):
    """#17: the Taxes tab's age is the saved plan's Likely age (ruling 16), which Home and Plan don't show as their
    headline age, so the line says which age it is and when the plan was saved, as Home now does."""
    make_ready_household(db)
    pi = build_inputs(db, TODAY)
    assert saved_plan_later_rate(db, TODAY, pi).line.startswith("From retiring at 65 (65 until a plan is saved), ")
    db.add(Plan(saved_at=datetime(2026, 10, 7, 19, 0, tzinfo=timezone.utc), saved_by=1, levers=LEVERS,
                engine_version=ENGINE_VERSION, comfortable_age=66, likely_age=63))
    db.commit()
    assert saved_plan_later_rate(db, TODAY, pi).line.startswith(
        "From retiring at 63 (the Likely age in the plan saved Oct 7), with required withdrawals from ")
    db.add(Plan(saved_at=datetime(2025, 12, 30, 19, 0, tzinfo=timezone.utc), saved_by=1, levers=LEVERS,
                engine_version=ENGINE_VERSION, comfortable_age=64, likely_age=None))
    db.commit()                                             # an older save, so the newest is still Oct 7's
    assert "(the Likely age in the plan saved Oct 7)" in saved_plan_later_rate(db, TODAY, pi).line
    db.add(Plan(saved_at=datetime(2026, 10, 12, 19, 0, tzinfo=timezone.utc), saved_by=1, levers=LEVERS,
                engine_version=ENGINE_VERSION, comfortable_age=64, likely_age=None))
    db.commit()
    assert "From retiring at 64 (the Comfortably age in the plan saved Oct 12)" in saved_plan_later_rate(db, TODAY, pi).line


def test_a_saved_plan_whose_levers_no_longer_parse_still_gives_its_age_with_default_levers(db):
    """An older save whose levers don't parse (empty, or pinning a lever since renamed) keeps its ages: the line still
    names the saved age, on default levers, and the Roth card and Next dollar still answer."""
    make_ready_household(db)
    pi = build_inputs(db, TODAY)
    for levers in ('{}', '{"assumed": {}, "try": {}, "pinned": ["a_lever_since_renamed"]}', 'not json'):
        db.query(Plan).delete()
        db.add(Plan(saved_at=datetime(2026, 10, 7, 19, 0, tzinfo=timezone.utc), saved_by=1, levers=levers,
                    engine_version=ENGINE_VERSION, comfortable_age=66, likely_age=63))
        db.commit()
        lr = saved_plan_later_rate(db, TODAY, pi)
        assert lr.line.startswith("From retiring at 63 (the Likely age in the plan saved Oct 7), "), levers
        assert lr.rate == later_rate(pi, Levers(), 63, "x").rate
        assert roth_view(db, TODAY).later == lr
        assert next_dollar._later_rate(db, TODAY, pi) == lr.rate


def test_a_plan_saved_in_another_year_says_the_year():
    assert roth.saved_label(datetime(2025, 12, 30, 19, 0, tzinfo=timezone.utc), TODAY) == "Dec 30, 2025"
    assert roth.saved_label(datetime(2026, 10, 8, 2, 0, tzinfo=timezone.utc), TODAY) == "Oct 7"   # the household's day


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
