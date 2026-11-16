"""care_projection (spec 4.5): read-only, dollar figures and years only, no names, parent books only."""
import json
from datetime import date

import pytest
from sqlalchemy.orm import Session

from steward.db.models import CareScenario, CareSetup, Transaction
from steward.demo_care import seed_care
from steward.demo_parent import seed_parent
from tests.advisor.helpers import call

TODAY = date(2026, 10, 19)


@pytest.fixture
def parent(margaret, books, mctx):
    engine = books.engine_for(margaret)
    with Session(engine) as db:
        seed_parent(db, TODAY, by=mctx.user_id)
        seed_care(db, TODAY)
    return engine, margaret, books.people(margaret.id), mctx.user_id


def run(p, name="care_projection", inp=None):
    engine, book, people, uid = p
    out = call(engine, book, people, uid, name, inp or {}, TODAY)
    assert out["error"] is None, out
    return out["content"]


def test_each_scenario_by_level_and_years(parent):
    out = run(parent)
    assert (out["set_up"], out["age"], out["medi_cal_limit_cents"], out["medi_cal_rules_year"]) == (True, 82, 13_000_000, 2026)
    assert [s["level"] for s in out["scenarios"]] == ["at_home", "in_home_help", "assisted_living", "nursing_home"]
    assert [s["n"] for s in out["scenarios"]] == [1, 2, 3, 4]
    home, help_, al, nh = out["scenarios"]
    assert (home["care_start_year"], home["care_monthly_cents"], home["medi_cal_year"]) == (None, 0, 2026)
    assert (help_["hours_a_week"], help_["care_start_year"]) == (20, 2026)
    assert (al["care_start_year"], al["care_cost_is_quote"], al["care_monthly_cents"], al["medi_cal_year"]) == (
        2027, True, 645_000, 2027)
    assert al["ltc_pays_from_year"] == 2027 and nh["home_sale_year"] == 2029
    # M7: two nursing home scenarios differ by room; in-home help by adult day days
    assert [(s["room"], s["adult_day_days"]) for s in out["scenarios"]] == [(None, None)] * 3 + [("shared", None)]
    for s in out["scenarios"]:
        assert (s["lasts_until_year"] is None) != (s["lasts_past_age"] is None)
        assert s["medi_cal_status"] in ("eligible", "over_limit", "after_spend_down")
    assert len(out["monthly"]["months"]) == 6 and out["monthly"]["months"][-1]["month"] == "2026-10"


def test_no_name_or_typed_word_reaches_the_result(parent):
    text = json.dumps(run(parent))
    for word in ("Margaret", "Robert", "Fullerton", "Evergreen", "Wells Fargo", "CareScout", "Place for Mom",
                 "Assisted living", "Social Security", "EDISON", "STATER"):
        assert word not in text, word


def test_before_setup_it_says_so(margaret, books, mctx):
    engine = books.engine_for(margaret)
    with Session(engine) as db:
        seed_parent(db, TODAY, by=mctx.user_id)
    out = call(engine, margaret, books.people(margaret.id), mctx.user_id, "care_projection", {}, TODAY)["content"]
    assert (out["set_up"], out["age"], out["scenarios"], out["medi_cal_limit_cents"]) == (False, None, [], None)
    assert len(out["monthly"]["months"]) == 6


def test_not_in_a_household_book(books, ours, mctx):
    out = call(books.engine_for(ours), ours, books.people(ours.id), mctx.user_id, "care_projection", {}, TODAY)
    assert out["error"] == "Not in this book."


def test_it_says_whether_any_spending_is_counted(parent, margaret, books, mctx):
    # final review I3: with no spending counted every scenario lasts longer, and Claude must be able to say so
    assert run(parent)["spending_counted"] is True
    engine = books.engine_for(margaret)
    with Session(engine) as db:
        db.query(Transaction).delete()
        db.commit()
    assert run(parent)["spending_counted"] is False
    with Session(engine) as db:
        db.get(CareSetup, 1).spending_monthly_cents = 0         # typed in, even as zero, is counted
        db.commit()
    assert run(parent)["spending_counted"] is True


def test_adult_day_days_go_as_a_number(parent, margaret, books):
    with Session(books.engine_for(margaret)) as db:
        db.query(CareScenario).filter(CareScenario.level == "in_home_help").update({"adult_day_days": 2})
        db.commit()
    help_ = run(parent)["scenarios"][1]
    assert (help_["level"], help_["adult_day_days"], help_["room"]) == ("in_home_help", 2, None)
