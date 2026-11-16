"""Spending's month (spec, Pages and API): the head, Everyday in the fixed order, Not sorted yet, Fixed costs,
payments made once in a while, Income."""
from datetime import date, datetime, timezone

from steward.db.models import SpendingTarget
from steward.services import spending as sp
from tests.factories import make_account, make_txn
from tests.spending_fixtures import TODAY, household

OCT, SEP = date(2026, 10, 1), date(2026, 9, 1)


def test_this_month_paces_everyday_against_its_targets_in_the_fixed_order(db):
    household(db)
    v = sp.month_view(db, TODAY, OCT)
    assert (v["month"], v["as_of"], v["current"], v["day"], v["days"], v["days_left"]) == (
        "2026-10", "2026-10-25", True, 25, 31, 6)
    assert v["earliest"] == "2026-04" and v["has_targets"] is True
    assert v["everyday"] == [
        {"category": "groceries", "kind": "everyday", "target_cents": 130_000, "spent_cents": 104_000,
         "refunds_cents": 0, "usual_by_today_cents": 104_839, "state": "on_track", "over_cents": 0,
         "over_level": "on", "typical_cents": 124_000, "order": 0},
        {"category": "dining", "kind": "everyday", "target_cents": 50_000, "spent_cents": 46_800,
         "refunds_cents": 1_384, "usual_by_today_cents": 40_323, "state": "on_track", "over_cents": 0,
         "over_level": "on", "typical_cents": 46_000, "order": 1},
        {"category": "shopping", "kind": "everyday", "target_cents": 40_000, "spent_cents": 51_200,
         "refunds_cents": 0, "usual_by_today_cents": 32_258, "state": "over", "over_cents": 11_200,
         "over_level": "clear", "typical_cents": 40_000, "order": 2},
        {"category": "personal", "kind": "everyday", "target_cents": None, "spent_cents": 8_400,
         "refunds_cents": 0, "usual_by_today_cents": None, "state": "none", "over_cents": None,
         "over_level": None, "typical_cents": 9_000, "order": 3},
    ]
    assert v["not_sorted"] == {"count": 2, "cents": 23_600}


def test_the_head_keeps_a_payment_made_once_in_a_while_out_of_the_plan_but_in_money_out(db):
    household(db)
    v = sp.month_view(db, TODAY, OCT)
    assert v["occasional"] == [{"category": "taxes", "kind": "occasional", "spent_cents": 421_000, "paid_on": "2026-10-20"}]
    assert v["income"] == [{"category": "income", "cents": 1_024_000}, {"category": "interest", "cents": 1_400}]
    assert v["head"] == {
        "spent_cents": 514_799, "planned_cents": 541_000, "everyday_spent_cents": 234_000,
        "everyday_target_cents": 220_000, "fixed_spent_cents": 280_799, "fixed_expected_cents": 321_000,
        "fixed_more_cents": 0, "fixed_not_yet": 1, "fixed_summary": "to_come", "occasional_cents": 421_000,
        "money_out_cents": 935_799, "income_cents": 1_025_400, "money_in_cents": 1_025_400, "set_aside_cents": 0, "paid_from_set_aside_cents": 0}
    assert v["set_aside"] is None


def test_a_finished_month_is_over_or_on_track_with_no_pace(db):
    household(db)
    v = sp.month_view(db, TODAY, SEP)
    assert (v["current"], v["day"], v["days"], v["days_left"]) == (False, None, 30, None)
    states = {r["category"]: (r["state"], r["usual_by_today_cents"]) for r in v["everyday"]}
    assert states == {"groceries": ("on_track", None), "dining": ("over", None), "shopping": ("on_track", None),
                      "personal": ("none", None)}
    assert [r["state"] for r in v["fixed"]] == ["as_usual", "as_usual", "as_usual"]   # Streamflix isn't new
    assert (v["head"]["spent_cents"], v["head"]["planned_cents"], v["head"]["fixed_summary"]) == (
        544_000, 541_000, "plain")
    assert v["occasional"] == []


def test_an_occasional_payment_nets_its_partial_refund(db):
    chk = household(db)["checking"]
    make_txn(db, chk, date(2026, 10, 22), 21_000, "COUNTY TAX REFUND", merchant="County tax collector",
             category="taxes")
    v = sp.month_view(db, TODAY, OCT)
    assert v["occasional"] == [{"category": "taxes", "kind": "occasional", "spent_cents": 400_000,
                                "paid_on": "2026-10-20"}]
    assert (v["head"]["occasional_cents"], v["head"]["money_out_cents"], v["head"]["spent_cents"]) == (
        400_000, 914_799, 514_799)


def test_a_kind_moves_a_category_between_the_figures(db):
    household(db)
    db.add(SpendingTarget(category="housing", kind="occasional", monthly_cents=None,
                          updated_at=datetime(2026, 10, 2, tzinfo=timezone.utc), updated_by=1))
    db.commit()
    v = sp.month_view(db, TODAY, OCT)
    assert [r["category"] for r in v["fixed"]] == ["utilities", "subscriptions"]
    assert [r["category"] for r in v["occasional"]] == ["taxes", "housing"]
    assert v["head"]["fixed_spent_cents"] == 12_799 and v["head"]["money_out_cents"] == 935_799


def test_refunds_bigger_than_spending_count_as_nothing_spent_and_take_nothing_from_the_rest(db):
    chk = make_account(db)
    make_txn(db, chk, date(2026, 10, 3), -4_000, "SHOE STORE", category="shopping")
    make_txn(db, chk, date(2026, 10, 9), 10_000, "SHOE STORE RETURN", category="shopping")
    make_txn(db, chk, date(2026, 10, 9), -2_500, "DINER", category="dining")
    v = sp.month_view(db, TODAY, OCT)
    shopping = next(r for r in v["everyday"] if r["category"] == "shopping")
    assert (shopping["spent_cents"], shopping["refunds_cents"], shopping["state"]) == (0, 10_000, "none")
    assert v["head"]["everyday_spent_cents"] == 2_500 and v["head"]["money_out_cents"] == 2_500


def test_a_young_book_takes_its_typical_month_from_the_months_it_has(db):
    chk = make_account(db)
    make_txn(db, chk, date(2026, 8, 1), -30_000, "DINER", category="dining")
    make_txn(db, chk, date(2026, 9, 1), -50_000, "DINER", category="dining")
    make_txn(db, chk, date(2026, 10, 2), -10_000, "DINER", category="dining")
    dining = next(r for r in sp.month_view(db, TODAY, OCT)["everyday"] if r["category"] == "dining")
    assert (dining["typical_cents"], dining["state"]) == (40_000, "none")


def test_a_book_with_only_this_month_has_no_typical_month_at_all(db):
    chk = make_account(db)
    make_txn(db, chk, date(2026, 10, 2), -10_000, "DINER", category="dining")
    v = sp.month_view(db, TODAY, OCT)
    assert v["everyday"] == [{"category": "dining", "kind": "everyday", "target_cents": None, "spent_cents": 10_000,
                              "refunds_cents": 0, "usual_by_today_cents": None, "state": "none",
                              "over_cents": None, "over_level": None, "typical_cents": None, "order": 0}]
    assert v["fixed"] == [] and v["head"]["fixed_summary"] == "none"
    assert (v["earliest"], v["has_targets"]) == ("2026-10", False)


def test_an_empty_book_answers_with_an_empty_month(db):
    v = sp.month_view(db, TODAY, OCT)
    assert v["everyday"] == [] and v["not_sorted"] == {"count": 0, "cents": 0} and v["earliest"] is None
    assert v["head"]["spent_cents"] == 0 and v["head"]["planned_cents"] == 0
