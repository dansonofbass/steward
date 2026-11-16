"""Over time and Set targets (spec, Pages and API): the groups, the suggestions, and saving only what changed with
one event_log line."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from steward.db.models import EventLog, SpendingTarget
from steward.services import spending as sp
from tests.factories import make_account, make_txn
from tests.spending_fixtures import AT, TODAY, household

NOW = datetime(2026, 10, 25, 17, 0, tzinfo=timezone.utc)


def test_over_time_lists_everyday_by_target_then_fixed_costs_that_vary(db):
    household(db)
    t = sp.trends_view(db, TODAY, 6)
    assert (t["months"], t["current"]) == (["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"], "2026-10")
    assert [(r["category"], r["group"]) for r in t["categories"]] == [
        ("groceries", "everyday"), ("dining", "everyday"), ("shopping", "everyday"), ("personal", "everyday"),
        ("utilities", "fixed"), ("housing", "steady"), ("subscriptions", "steady"), ("taxes", "occasional")]
    assert t["categories"][2] == {
        "category": "shopping", "kind": "everyday", "group": "everyday", "target_cents": 40_000, "expected_cents": None,
        "typical_cents": 40_000, "spent": [45_000, 41_000, 39_000, 43_000, 39_000, 51_200], "over_in": 3,
        "over_of": 6, "order": 2}
    dining = t["categories"][1]
    assert (dining["spent"], dining["over_in"]) == ([62_000, 38_000, 44_000, 47_000, 51_000, 46_800], 2)
    utilities = t["categories"][4]
    assert (utilities["expected_cents"], utilities["spent"][-1]) == (41_000, 0)
    assert t["categories"][-1]["spent"] == [0, 0, 0, 0, 0, 421_000]
    assert [r["order"] for r in t["categories"]] == list(range(8))
    assert len(sp.trends_view(db, TODAY, 12)["months"]) == 12


def test_a_fixed_cost_with_nothing_to_judge_it_by_is_neither_steady_nor_varying(db):
    """Rulings 17, 21 and 24: one $50 payment in six months types Insurance and Giving at $0. Insurance (no amount
    set) has no expectation, so it is not named "the same every month": it comes back unjudged, with its months for
    its category page; Giving, set to $0 by hand, varies from it. Fees, set to $0 and paid only in April (in the
    window, before the 6-month span), has nothing to draw."""
    accounts = household(db)
    for c in ("insurance", "giving"):
        make_txn(db, accounts["checking"], date(2026, 6, 15), -5_000, "PAYMENT", merchant="Someone", category=c)
    make_txn(db, accounts["checking"], date(2026, 4, 15), -5_000, "BANK FEE", merchant="Bank", category="fees")
    for c in ("giving", "fees"):
        db.add(SpendingTarget(category=c, kind="fixed", monthly_cents=0, updated_at=AT, updated_by=1))
    db.commit()
    by = {r["category"]: r for r in sp.trends_view(db, TODAY, 6)["categories"]}
    assert "fees" not in by
    assert (by["insurance"]["group"], by["insurance"]["expected_cents"], by["insurance"]["spent"]) == (
        "unjudged", None, [0, 5_000, 0, 0, 0, 0])
    assert (by["giving"]["expected_cents"], by["giving"]["target_cents"], by["giving"]["group"]) == (0, 0, "fixed")
    twelve = {r["category"]: r for r in sp.trends_view(db, TODAY, 12)["categories"]}
    assert (twelve["fees"]["group"], twelve["fees"]["spent"][5]) == ("fixed", 5_000)    # April is in 12 months' span


def test_a_young_books_fixed_costs_are_not_called_the_same_every_month(db):
    """Ruling 24: a book whose only data is this month has no window, so no fixed cost is steady or varying, even one
    with an amount set. Both come back unjudged with this month drawn; a fixed cost with nothing paid and nothing
    expected does not come back at all."""
    chk = make_account(db, "Checking")
    make_txn(db, chk, date(2026, 10, 1), -268_000, "HOMELOAN", merchant="Home loan", category="housing")
    make_txn(db, chk, date(2026, 10, 12), -41_000, "CITY POWER", merchant="City Power", category="utilities")
    make_txn(db, chk, date(2026, 10, 10), -4_000, "NOODLE HOUSE", merchant="Noodle House", category="dining")
    db.add(SpendingTarget(category="housing", kind="fixed", monthly_cents=268_000, updated_at=AT, updated_by=1))
    db.commit()
    t = sp.trends_view(db, TODAY, 6)
    assert [(r["category"], r["group"], r["expected_cents"], r["spent"][-1]) for r in t["categories"]] == [
        ("dining", "everyday", None, 4_000), ("housing", "unjudged", 268_000, 268_000),
        ("utilities", "unjudged", None, 41_000)]


def test_over_time_on_a_young_book_counts_over_of_its_window(db):
    """A book with three complete months says "over in N of the last 3", not of 6 or of 12."""
    card = make_account(db, "Card", type="credit")
    for m, cents in ((7, 52_000), (8, 47_000), (9, 55_000), (10, 20_000)):
        make_txn(db, card, date(2026, m, 1), -cents, "NOODLE HOUSE", merchant="Noodle House", category="dining")
    db.add(SpendingTarget(category="dining", kind="everyday", monthly_cents=50_000, updated_at=AT, updated_by=1))
    db.commit()
    assert sp.window_sums(db, TODAY)[0] == ["2026-07", "2026-08", "2026-09"]
    (dining,) = sp.trends_view(db, TODAY, 6)["categories"]
    assert (dining["over_in"], dining["over_of"], dining["spent"]) == (2, 3, [0, 0, 52_000, 47_000, 55_000, 20_000])
    (dining,) = sp.trends_view(db, TODAY, 12)["categories"]
    assert (dining["over_in"], dining["over_of"]) == (2, 3)


def test_over_time_counts_the_last_6_or_12_complete_months(db):
    """The count follows the 6 or 12 chosen: the last 6 or 12 complete months with data (this month never). Dining
    went over $500 three times from October 2025 to March 2026 and twice from April to September 2026; September
    2025, over too, is a 13th month back. In 6 months it is over in 2 of 6; in 12 it is over
    in 5 of 12. The typical month is the last 6 either way."""
    card = make_account(db, "Card", type="credit")
    older = (90_000, 60_000, 40_000, 70_000, 45_000, 30_000, 55_000)     # September 2025 to March 2026
    recent = (52_000, 40_000, 45_000, 48_000, 56_000, 30_000)            # April to September 2026
    for i, cents in enumerate(older + recent):
        y, m = (2025, 9 + i) if i < 4 else (2026, i - 3)
        make_txn(db, card, date(y, m, 2), -cents, "NOODLE HOUSE", merchant="Noodle House", category="dining")
    make_txn(db, card, date(2026, 10, 2), -80_000, "NOODLE HOUSE", merchant="Noodle House", category="dining")
    db.add(SpendingTarget(category="dining", kind="everyday", monthly_cents=50_000, updated_at=AT, updated_by=1))
    db.commit()
    (six,) = sp.trends_view(db, TODAY, 6)["categories"]
    (twelve,) = sp.trends_view(db, TODAY, 12)["categories"]
    assert (six["over_in"], six["over_of"], six["group"]) == (2, 6, "everyday")
    assert (twelve["over_in"], twelve["over_of"], twelve["group"]) == (5, 12, "everyday")
    assert six["typical_cents"] == twelve["typical_cents"] == 47_000
    # As in 6 months, the bars are this month and the 11 before it, so the oldest month counted (October 2025) is
    # the one before the first bar.
    assert twelve["spent"] == [*older[2:], *recent, 80_000]


def test_over_time_in_twelve_months_skips_a_month_without_data(db):
    """As the typical month does (ruling 1): a gap month is skipped and an older one taken, so 12 months of data
    reach back past the gap."""
    card = make_account(db, "Card", type="credit")
    months = [(2025, m) for m in range(8, 13)] + [(2026, m) for m in (1, 2, 3, 5, 6, 7, 8, 9)]   # no April 2026
    for y, m in months:
        make_txn(db, card, date(y, m, 2), -60_000, "NOODLE HOUSE", merchant="Noodle House", category="dining")
    db.add(SpendingTarget(category="dining", kind="everyday", monthly_cents=50_000, updated_at=AT, updated_by=1))
    db.commit()
    assert sp.window_sums(db, TODAY, 12)[0][0] == "2025-09"
    (dining,) = sp.trends_view(db, TODAY, 12)["categories"]
    assert (dining["over_in"], dining["over_of"]) == (12, 12)


def test_targets_list_every_category_with_its_typical_month_and_suggestion(db):
    household(db)
    v = sp.targets_view(db, TODAY)
    assert [r["category"] for r in v["categories"]] == [
        "groceries", "dining", "shopping", "personal", "transport", "travel", "health", "cash_atm", "pets",
        "home", "gifts", "entertainment", "business_expense", "fees",
        "housing", "utilities", "subscriptions", "insurance", "loan_payments", "childcare_education", "giving", "kids",
        "taxes"]
    by = {r["category"]: r for r in v["categories"]}
    assert by["groceries"] == {"category": "groceries", "kind": "everyday", "monthly_cents": 130_000,
                               "typical_cents": 124_000, "usual_cents": 124_000, "suggested_cents": 124_000,
                               "low_cents": 124_000,
                               "high_cents": 124_000, "order": 0}
    assert by["travel"] == {"category": "travel", "kind": "everyday", "monthly_cents": None, "typical_cents": 0,
                            "usual_cents": None, "suggested_cents": None, "low_cents": 0, "high_cents": 0, "order": 5}
    assert (by["utilities"]["kind"], by["utilities"]["low_cents"], by["utilities"]["high_cents"]) == ("fixed", 36_000, 52_000)
    assert (v["updated_at"], v["updated_by_id"], v["has_targets"]) == (AT.isoformat(), 1, True)
    assert v["typical_income_cents"] == 512_000


def test_targets_of_a_new_book_suggest_nothing(db):
    v = sp.targets_view(db, TODAY)
    assert all(r["typical_cents"] is None and r["suggested_cents"] is None and r["low_cents"] is None
               for r in v["categories"])
    assert (v["updated_at"], v["updated_by_id"], v["has_targets"], v["typical_income_cents"]) == (None, None, False, None)


def test_a_change_of_kind_alone_is_not_a_target(db):
    """Ruling 11: has_targets counts only rows with an amount, so a kind-only change keeps the first-time notice."""
    sp.save_targets(db, [("groceries", "fixed", None)], user_id=7, who="Alex", at=NOW)
    db.commit()
    v = sp.targets_view(db, TODAY)
    assert (v["has_targets"], v["updated_at"], v["updated_by_id"]) == (False, NOW.isoformat(), 7)


def test_saving_writes_only_what_changed_and_one_event(db):
    changes = sp.save_targets(db, [("groceries", "everyday", 130_000), ("housing", "fixed", None),
                                   ("subscriptions", "everyday", 12_000)],
                              user_id=7, who="Alex", at=NOW)
    db.commit()
    assert changes == ["Groceries no target → $1,300", "Subscriptions bill → flexible, the typical month → $120"]
    assert db.get(SpendingTarget, "housing") is None                      # unchanged, so no row
    row = db.get(SpendingTarget, "groceries")
    assert (row.kind, row.monthly_cents, row.updated_by, row.updated_at) == ("everyday", 130_000, 7, NOW)
    events = db.scalars(select(EventLog).where(EventLog.kind == "spending")).all()
    assert [(e.level, e.actionable, e.message) for e in events] == [("info", False,
        "Alex changed Spending: Groceries no target → $1,300; Subscriptions bill → flexible, the typical month → $120.")]
    assert sp.save_targets(db, [("groceries", "everyday", 130_000)], user_id=7, who="Alex", at=NOW) == []
    db.commit()
    assert len(db.scalars(select(EventLog).where(EventLog.kind == "spending")).all()) == 1


def test_an_unchanged_row_keeps_its_time_when_others_in_the_same_save_change(db):
    household(db)
    assert sp.save_targets(db, [("groceries", "everyday", 130_000), ("dining", "everyday", 55_000)],
                           user_id=7, who="Alex", at=NOW) == ["Eating out $500 → $550"]
    db.commit()
    groceries, dining = db.get(SpendingTarget, "groceries"), db.get(SpendingTarget, "dining")
    assert (groceries.updated_at, groceries.updated_by) == (AT, 1)
    assert (dining.monthly_cents, dining.updated_at, dining.updated_by) == (55_000, NOW, 7)


def test_a_change_of_kind_with_no_amount_either_side_names_only_the_kind(db):
    """Ruling 4: as the save bar words it ("Subscriptions fixed → everyday"), without "the typical month → no
    target"."""
    assert sp.save_targets(db, [("subscriptions", "everyday", None), ("taxes", "fixed", None)],
                           user_id=7, who="Alex", at=NOW) == [
        "Subscriptions bill → flexible", "Taxes once in a while → bill"]


def test_a_target_of_0_is_kept_as_0_and_clearing_it_leaves_none(db):
    """Ruling 21: $0 is an expectation of $0, stored as 0; clearing a target stores null."""
    def save(*targets):
        return sp.save_targets(db, list(targets), user_id=7, who="Alex", at=NOW)

    assert save(("dining", "everyday", 50_000), ("utilities", "fixed", 0)) == [
        "Eating out no target → $500", "Utilities the typical month → $0"]
    assert db.get(SpendingTarget, "utilities").monthly_cents == 0
    assert save(("dining", "everyday", 0)) == ["Eating out $500 → $0"]
    assert db.get(SpendingTarget, "dining").monthly_cents == 0
    assert save(("dining", "everyday", None), ("utilities", "fixed", None)) == [
        "Eating out $0 → no target", "Utilities $0 → the typical month"]
    assert (db.get(SpendingTarget, "dining").monthly_cents, db.get(SpendingTarget, "utilities").monthly_cents) == (
        None, None)


def test_cents_that_are_not_whole_dollars_are_shown_with_cents(db):
    assert sp.save_targets(db, [("dining", "everyday", 47_050)], user_id=7, who="Alex", at=NOW) == ["Eating out no target → $470.50"]


@pytest.mark.parametrize("body, message", [
    ([], sp.NOT_UNDERSTOOD),
    ({}, sp.NOT_UNDERSTOOD),
    ({"targets": "x"}, sp.NOT_UNDERSTOOD),
    ({"targets": ["dining"]}, sp.NOT_UNDERSTOOD),
    ({"targets": [{"category": "income", "kind": "everyday", "monthly_cents": 1}]}, sp.NOT_A_CATEGORY),
    ({"targets": [{"category": ["dining"], "kind": "everyday"}]}, sp.NOT_A_CATEGORY),
    ({"targets": [{"category": "dining", "kind": "weekly", "monthly_cents": 1}]}, sp.BAD_KIND),
    ({"targets": [{"category": "dining", "kind": "everyday", "monthly_cents": -1}]}, sp.BAD_CENTS),
    ({"targets": [{"category": "dining", "kind": "everyday", "monthly_cents": 100_000_001}]}, sp.BAD_CENTS),
    ({"targets": [{"category": "dining", "kind": "everyday", "monthly_cents": "500"}]}, sp.BAD_CENTS),
    ({"targets": [{"category": "dining", "kind": "everyday", "monthly_cents": 12.5}]}, sp.BAD_CENTS),
    ({"targets": [{"category": "dining", "kind": "everyday", "monthly_cents": True}]}, sp.BAD_CENTS),
    ({"targets": [{"category": "taxes", "kind": "occasional", "monthly_cents": 100}]}, sp.OCCASIONAL_HAS_NO_TARGET),
    ({"targets": [{"category": "dining", "kind": "everyday"}, {"category": "dining", "kind": "fixed"}]}, sp.LISTED_TWICE),
])
def test_parse_refuses_in_plain_words(body, message):
    with pytest.raises(sp.TargetsError) as e:
        sp.parse_targets(body)
    assert str(e.value) == message


def test_parse_reads_a_good_body_and_ignores_prefs():
    targets = sp.parse_targets({"targets": [{"category": "dining", "kind": "everyday", "monthly_cents": 50_000},
                                            {"category": "housing", "kind": "fixed", "monthly_cents": None},
                                            {"category": "taxes", "kind": "occasional"},
                                            {"category": "giving", "kind": "commitment", "monthly_cents": 0}],
                                "prefs": {"warn_pct_bp": 0, "warn_min_cents": 100_000}})
    assert targets == [("dining", "everyday", 50_000), ("housing", "fixed", None), ("taxes", "occasional", None),
                       ("giving", "commitment", 0)]
