"""Polish round, item 2: a Flexible row is over by this month's facts only (on, a little, clearly), and on days 1-7
only clearly over shows; the monthly target check asks about a target below a typical month that was missed in 4 of
the last 6, one at a time, biggest gap first, until kept; Set and Keep take one Undo each, and Check again too;
suggestions are the 75th percentile rounded up to $10; running ahead and the pattern group are gone."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from steward.db.models import EventLog, SpendingTarget
from steward.services import spending as sp
from tests.factories import make_account, make_txn
from tests.spending_fixtures import TODAY, household

OCT, SEP = date(2026, 10, 1), date(2026, 9, 1)
AT = datetime(2026, 10, 1, 17, 0, tzinfo=timezone.utc)
OCT_25 = datetime(2026, 10, 25, 19, 0, tzinfo=timezone.utc)
CHECK = {"category": "dining", "target_cents": 30_000, "typical_cents": 41_000}


@pytest.mark.parametrize("spent, target, day, want", [
    (50_499, 50_000, None, (499, "on")),         # $4.99 over is on target
    (50_500, 50_000, None, (500, "little")),     # $5
    (52_500, 50_000, None, (2_500, "little")),   # $25
    (30_301, 27_800, None, (2_501, "little")),   # $25.01, but 9% of the target
    (26_200, 23_600, None, (2_600, "clear")),    # $26 and 11%
    (40_000, 50_000, None, (0, "on")),           # under the target
    (52_500, 50_000, 7, (2_500, "on")),          # day 7: a little over is on target
    (52_500, 50_000, 8, (2_500, "little")),      # day 8
    (60_000, 50_000, 3, (10_000, "clear")),      # clearly over shows from day 1
])
def test_over_levels_at_their_edges(spent, target, day, want):
    assert sp.over_level(spent, target, day) == want


def test_flexible_rows_carry_their_over_cents_and_level_and_no_prefs(db):
    household(db)
    v = sp.month_view(db, TODAY, OCT)
    got = {r["category"]: (r["state"], r["over_cents"], r["over_level"]) for r in v["everyday"]}
    assert got == {"groceries": ("on_track", 0, "on"), "dining": ("on_track", 0, "on"),
                   "shopping": ("over", 11_200, "clear"), "personal": ("none", None, None)}
    assert "prefs" not in v and v["target_check"] is None


def dining(db, acct, amounts, category="dining", merchant="Noodle House"):
    for m, cents in zip((4, 5, 6, 7, 8, 9), amounts):
        make_txn(db, acct, date(2026, m, 1), -cents, merchant.upper(), merchant=merchant, category=category)


def target(db, category, cents, check_after=None):
    db.add(SpendingTarget(category=category, kind="everyday", monthly_cents=cents, updated_at=AT, updated_by=1,
                          check_after=check_after))
    db.commit()


@pytest.fixture
def check_book(db):
    card = make_account(db, "Card", type="credit")
    dining(db, card, (42_000, 45_000, 28_000, 44_000, 40_000, 31_000))   # typical $410; over $300 in 4 of 6
    target(db, "dining", 30_000)
    return card


def test_the_check_asks_about_a_target_below_typical_missed_in_4_of_6(db, check_book):
    assert sp.target_check(db, TODAY) == CHECK
    assert sp.month_view(db, TODAY, OCT)["target_check"] == CHECK
    assert sp.month_view(db, TODAY, SEP)["target_check"] is None           # the current month only


def test_3_of_6_misses_or_a_target_at_typical_asks_nothing(db):
    card = make_account(db, "Card", type="credit")
    dining(db, card, (42_000, 45_000, 28_000, 44_000, 29_000, 30_000))   # over $300 in 3 of 6
    target(db, "dining", 30_000)
    assert sp.target_check(db, TODAY) is None
    dining(db, card, (40_100,) * 6, category="shopping", merchant="Megamart")    # typical $400, over in all 6
    target(db, "shopping", 40_050)                                               # at or above typical
    assert sp.target_check(db, TODAY) is None
    db.get(SpendingTarget, "shopping").monthly_cents = 39_000
    db.commit()
    assert sp.target_check(db, TODAY) == {"category": "shopping", "target_cents": 39_000, "typical_cents": 40_000}


def test_a_kept_target_comes_back_on_its_day(db, check_book):
    db.get(SpendingTarget, "dining").check_after = date(2026, 10, 26)
    db.commit()
    assert sp.target_check(db, TODAY) is None
    assert sp.target_check(db, date(2026, 10, 26)) == CHECK


def test_the_biggest_gap_is_asked_first_and_one_at_a_time(db, check_book):
    dining(db, check_book, (25_000, 26_000, 27_000, 28_000, 10_000, 10_000), category="shopping", merchant="Megamart")
    target(db, "shopping", 20_000)                                       # typical $260: a $60 gap against $110
    assert sp.target_check(db, TODAY)["category"] == "dining"
    db.get(SpendingTarget, "dining").check_after = date(2027, 1, 1)
    db.commit()
    assert sp.target_check(db, TODAY) == {"category": "shopping", "target_cents": 20_000, "typical_cents": 26_000}


def test_any_change_to_the_target_clears_check_after(db, check_book):
    db.get(SpendingTarget, "dining").check_after = date(2027, 1, 1)
    db.commit()
    sp.save_targets(db, [("dining", "everyday", 32_000)], user_id=1, who="JR", at=AT)
    db.commit()
    assert db.get(SpendingTarget, "dining").check_after is None


def test_suggested_targets_are_the_75th_percentile_rounded_up_to_10_dollars():
    assert sp.suggested_cents([40_100]) == 41_000 and sp.suggested_cents([40_000]) == 40_000
    assert sp.suggested_cents([10_000, 20_000]) == 20_000
    assert sp.suggested_cents([10_000, 20_000, 30_000]) == 30_000
    assert sp.suggested_cents([10_000, 20_000, 30_000, 40_000]) == 30_000
    assert sp.suggested_cents([10_000, 20_000, 30_000, 40_000, 50_000]) == 40_000
    assert sp.suggested_cents([60_000, 10_000, 50_000, 20_000, 40_000, 30_000]) == 50_000   # the 5th of 6
    assert sp.suggested_cents([0, 0, 0]) is None and sp.suggested_cents([]) is None


def test_targets_suggest_p75_and_list_kept_targets(db):
    household(db)
    v = sp.targets_view(db, TODAY)
    by = {r["category"]: r for r in v["categories"]}
    assert (by["dining"]["suggested_cents"], by["shopping"]["suggested_cents"], by["groceries"]["suggested_cents"]) == (
        51_000, 43_000, 124_000)
    assert by["dining"]["typical_cents"] == 46_000 and by["travel"]["suggested_cents"] is None
    assert "prefs" not in v and v["kept"] == []
    db.get(SpendingTarget, "dining").check_after = date(2027, 1, 1)
    db.get(SpendingTarget, "shopping").check_after = TODAY                 # due today: no longer kept
    db.commit()
    assert sp.targets_view(db, TODAY)["kept"] == [{"category": "dining", "target_cents": 50_000, "until": "2027-01-01"}]


@pytest.fixture
def oct25(monkeypatch):
    monkeypatch.setattr("steward.clock.now", lambda: OCT_25)


def messages(db):
    db.rollback()
    db.expire_all()
    return [e.message for e in db.scalars(select(EventLog).where(EventLog.kind == "spending").order_by(EventLog.id))]


def test_set_writes_the_typical_month_with_one_undo(oct25, signed_in, db, check_book):
    r = signed_in.post("/api/b/ours/spending/targets/dining/check", json={"answer": "set", "target_cents": 30_000})
    assert r.status_code == 200
    body = r.json()
    assert (body["target_cents"], body["until"]) == (41_000, None) and body["undo"]
    assert messages(db) == ["JR changed Spending: Eating out $300 → $410."]
    assert db.get(SpendingTarget, "dining").monthly_cents == 41_000
    assert signed_in.get("/api/b/ours/spending").json()["target_check"] is None
    assert signed_in.post(f"/api/b/ours/undo/{body['undo']}").status_code == 200
    db.rollback()                          # end the read snapshot taken before the Undo
    db.expire_all()
    assert db.get(SpendingTarget, "dining").monthly_cents == 30_000


def test_keep_waits_three_months_and_check_again_asks_again(oct25, signed_in, db, check_book):
    r = signed_in.post("/api/b/ours/spending/targets/dining/check", json={"answer": "keep", "target_cents": 30_000})
    assert r.status_code == 200 and (r.json()["target_cents"], r.json()["until"]) == (30_000, "2027-01-01")
    assert messages(db) == ["JR kept Eating out's target at $300 until Jan 2027."]
    row = db.get(SpendingTarget, "dining")
    assert (row.check_after, row.monthly_cents, row.updated_at) == (date(2027, 1, 1), 30_000, AT)   # the target didn't change
    assert signed_in.get("/api/b/ours/spending").json()["target_check"] is None
    assert signed_in.get("/api/b/ours/spending/targets").json()["kept"] == [
        {"category": "dining", "target_cents": 30_000, "until": "2027-01-01"}]
    again = signed_in.delete("/api/b/ours/spending/targets/dining/kept")
    assert again.status_code == 200 and again.json()["undo"]
    assert messages(db)[-1] == "JR asked Steward to check Eating out's target again."
    assert signed_in.get("/api/b/ours/spending").json()["target_check"] == CHECK
    r = signed_in.delete("/api/b/ours/spending/targets/dining/kept")
    assert r.status_code == 404 and r.json() == {"error": "That target isn't kept."}
    assert signed_in.post(f"/api/b/ours/undo/{again.json()['undo']}").status_code == 200
    db.rollback()                          # end the read snapshot taken before the Undo
    db.expire_all()
    assert db.get(SpendingTarget, "dining").check_after == date(2027, 1, 1)


def test_the_check_refuses_in_plain_words(oct25, signed_in, db, check_book):
    post = lambda c, body: signed_in.post(f"/api/b/ours/spending/targets/{c}/check", json=body)   # noqa: E731
    r = post("dining", {"answer": "set", "target_cents": 25_000})
    assert r.status_code == 409 and r.json() == {"error": "That target changed since."}
    for body in ({"answer": "maybe", "target_cents": 30_000}, {"answer": "set"}, {"answer": "set", "target_cents": True}):
        r = post("dining", body)
        assert r.status_code == 422 and r.json() == {"error": "That request wasn't understood."}
    r = post("income", {"answer": "keep", "target_cents": 30_000})
    assert r.status_code == 404 and r.json() == {"error": "That isn't a category Spending tracks."}
    r = post("shopping", {"answer": "keep", "target_cents": 30_000})               # no target at all
    assert r.status_code == 409
    assert messages(db) == []


def test_a_body_with_the_old_prefs_still_saves_and_ignores_them(oct25, signed_in, db):
    body = {"targets": [{"category": "groceries", "kind": "everyday", "monthly_cents": 125_000}],
            "prefs": {"warn_pct_bp": 99_999, "warn_min_cents": -1}}
    r = signed_in.put("/api/b/ours/spending/targets", json=body)
    assert r.status_code == 200 and "prefs" not in r.json()


@pytest.mark.parametrize("answer, line", [("set", "JR changed Spending: Eating out $300 → $410."),
                                          ("keep", "JR kept Eating out's target at $300 until Jan 2027.")])
def test_undoing_set_or_keep_leaves_its_log_line(oct25, signed_in, db, check_book, answer, line):
    r = signed_in.post("/api/b/ours/spending/targets/dining/check", json={"answer": answer, "target_cents": 30_000})
    assert messages(db) == [line]
    assert signed_in.post(f"/api/b/ours/undo/{r.json()['undo']}").status_code == 200
    assert messages(db) == [line]                    # Undo puts the target back; the audit log keeps the line
    row = db.get(SpendingTarget, "dining")
    assert (row.monthly_cents, row.check_after) == (30_000, None)
