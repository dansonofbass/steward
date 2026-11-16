"""Polish round, item 1: a check means paid; usual is the middle of the months with a payment; a Bill or a Commitment
is expected when paid in 4 of the last 6 months; different from usual is $25 and 10%; only a Bill turns amber; the
head says "more than usual" over Bills only; Giving outside these accounts never touches money out."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from steward.db.models import EventLog, SpendingTarget, Transaction
from steward.services import spending as sp
from tests.factories import add_fact, make_account, make_txn
from tests.spending_fixtures import TODAY, household

OCT, SEP = date(2026, 10, 1), date(2026, 9, 1)
AT = datetime(2026, 10, 2, tzinfo=timezone.utc)
OCT_25 = datetime(2026, 10, 25, 19, 0, tzinfo=timezone.utc)
WINDOW = (4, 5, 6, 7, 8, 9)


def row(v, c):
    return next(r for r in v["fixed"] if r["category"] == c)


def paid(db, acct, category, merchant, months, cents, day=12):
    for m in months:
        make_txn(db, acct, date(2026, m, day), -cents, merchant.upper(), merchant=merchant, category=category)


def test_different_from_usual_is_25_dollars_and_10_percent():
    assert not sp.differs_from_usual(12_499, 10_000) and sp.differs_from_usual(12_500, 10_000)     # $24.99 vs $25.00
    assert not sp.differs_from_usual(109_900, 100_000) and sp.differs_from_usual(110_000, 100_000)  # 9.9% vs 10.0%
    assert not sp.differs_from_usual(52_500, 50_000)                                               # $25 but 5%
    assert sp.differs_from_usual(7_500, 10_000) and not sp.differs_from_usual(8_000, 10_000)        # under counts too


def test_usual_is_the_middle_of_the_months_with_a_payment():
    assert sp.usual_cents([41_000, 0, 43_000, 0, 0, 0]) == 42_000          # a $0 month is left out
    assert sp.typical_cents([41_000, 0, 43_000, 0, 0, 0]) == 0             # the typical month counts it
    assert sp.usual_cents([0, 0]) is None and sp.usual_cents([]) is None
    assert sp.usual_cents([12_340]) == 12_000
    assert sp.usual_of(sp.Setting("fixed", 50_000), [41_000]) == 50_000     # a set amount wins (P5)
    assert sp.usual_of(sp.Setting("fixed", None), [41_000]) == 41_000


def test_expected_is_4_of_6_months_or_a_set_amount():
    assert not sp.is_expected(sp.Setting("fixed", None), [1, 1, 1, 0, 0, 0])
    assert sp.is_expected(sp.Setting("fixed", None), [1, 1, 1, 1, 0, 0])
    assert sp.is_expected(sp.Setting("fixed", 100), [])
    assert not sp.is_expected(sp.Setting("fixed", 0), [])                  # a set $0 expects no payment


@pytest.mark.parametrize("kind, spent, usual, expected, paid, usual_day, day, days, new, want", [
    ("fixed", 0, 45_000, True, False, 15, 19, 31, False, ("waiting", "ring")),        # usual day + 4
    ("fixed", 0, 45_000, True, False, 15, 20, 31, False, ("late", "amber")),          # usual day + 5
    ("commitment", 0, 14_000, True, False, 15, 20, 31, False, ("late", "ring")),      # a Commitment is never amber
    ("fixed", 0, 45_000, True, False, 28, 29, 30, False, ("waiting", "ring")),        # capped at the month's last day
    ("fixed", 0, 45_000, True, False, 28, 30, 30, False, ("late", "amber")),
    ("fixed", 0, 45_000, True, False, None, 30, 30, False, ("waiting", "ring")),      # no usual day: never late
    ("fixed", 32_800, 45_000, True, True, 15, 20, 31, False, ("so_far", "ring")),
    ("fixed", 32_800, 45_000, True, True, 15, None, 31, False, ("under", "check")),   # a closed month
    ("fixed", 54_000, 45_000, True, True, 15, 20, 31, False, ("over", "amber")),
    ("commitment", 30_000, 14_000, True, True, 3, None, 31, False, ("over", "check")),
    ("fixed", 45_500, 45_000, True, True, 15, 20, 31, False, ("as_usual", "check")),
    ("fixed", 45_500, 45_000, True, True, 15, 20, 31, True, ("as_usual", "amber")),   # a new payee: the amber dot
    ("fixed", 32_800, 45_000, True, True, 15, 20, 31, True, ("so_far", "amber")),     # stacked: amber over dashed
    ("commitment", 14_000, 14_000, True, True, 3, 20, 31, True, ("as_usual", "check")),
    ("fixed", 0, 45_000, True, False, 15, None, 31, False, ("none", "quiet")),        # closed, nothing paid
    ("fixed", 90_000, 45_000, False, True, 15, 20, 31, False, ("as_usual", "check")), # not expected: amount only
    ("fixed", 9_000, None, True, True, None, 20, 31, False, ("as_usual", "check")),   # nothing to judge by
])
def test_fixed_states_and_tones(kind, spent, usual, expected, paid, usual_day, day, days, new, want):
    assert sp.fixed_state(kind, spent, usual, expected=expected, paid=paid, usual_day=usual_day, day=day, days=days,
                          new_payee=new) == want


def test_the_fixtures_bills_this_month(db):
    household(db)
    v = sp.month_view(db, TODAY, OCT)
    assert v["fixed"] == [
        {"category": "housing", "kind": "fixed", "expected": True, "expected_cents": 268_000, "usual_cents": 268_000,
         "spent_cents": 268_000, "refunds_cents": 0, "state": "as_usual", "tone": "check", "came_out_on": "2026-10-01",
         "merchant": "Home loan", "typical_day": 1, "new_payee": None},
        {"category": "utilities", "kind": "fixed", "expected": True, "expected_cents": 41_000, "usual_cents": 41_000,
         "spent_cents": 0, "refunds_cents": 0, "state": "late", "tone": "amber", "came_out_on": None, "merchant": None,
         "typical_day": 12, "new_payee": None},
        {"category": "subscriptions", "kind": "fixed", "expected": True, "expected_cents": 12_000,
         "usual_cents": 12_000, "spent_cents": 12_799, "refunds_cents": 0, "state": "as_usual", "tone": "amber",
         "came_out_on": "2026-10-03", "merchant": "Streamflix", "typical_day": 3,
         "new_payee": {"name": "StreamBox", "cents": 799}},
    ]
    h = v["head"]
    assert (h["fixed_summary"], h["fixed_not_yet"], h["fixed_more_cents"]) == ("to_come", 1, 0)
    assert "fixed_differs" not in h
    assert v["kinds"]["giving"] == "commitment" and v["kinds"]["housing"] == "fixed" and v["kinds"]["dining"] == "everyday"


def test_waiting_until_usual_day_plus_5_then_late_and_a_commitment_stays_neutral(db):
    chk = make_account(db, "Checking")
    paid(db, chk, "utilities", "City Power", WINDOW, 41_000)
    paid(db, chk, "giving", "Grace Community", WINDOW, 14_000)
    v16 = sp.month_view(db, date(2026, 10, 16), OCT)
    assert [(r["category"], r["state"], r["tone"]) for r in v16["fixed"]] == [
        ("utilities", "waiting", "ring"), ("giving", "waiting", "ring")]
    v17 = sp.month_view(db, date(2026, 10, 17), OCT)
    assert [(r["category"], r["state"], r["tone"]) for r in v17["fixed"]] == [
        ("utilities", "late", "amber"), ("giving", "late", "ring")]


def test_so_far_on_the_last_day_and_under_once_the_month_closes(db):
    chk = make_account(db, "Checking")
    paid(db, chk, "utilities", "City Power", WINDOW, 41_000)
    make_txn(db, chk, date(2026, 10, 12), -30_000, "CITY POWER", merchant="City Power", category="utilities")
    last_day = row(sp.month_view(db, date(2026, 10, 31), OCT), "utilities")
    assert (last_day["state"], last_day["tone"], last_day["usual_cents"]) == ("so_far", "ring", 41_000)
    closed = sp.month_view(db, date(2026, 11, 1), OCT)
    assert (row(closed, "utilities")["state"], row(closed, "utilities")["tone"]) == ("under", "check")
    assert closed["head"]["fixed_summary"] == "plain"


def test_a_bill_paid_in_3_of_6_months_isnt_expected(db):
    chk = make_account(db, "Checking")
    paid(db, chk, "groceries", "Greenleaf", WINDOW, 10_000, day=1)              # every window month has data
    paid(db, chk, "insurance", "Big Mutual", (4, 6, 8), 36_000)
    assert "insurance" not in {r["category"] for r in sp.month_view(db, TODAY, OCT)["fixed"]}
    make_txn(db, chk, date(2026, 10, 9), -80_000, "BIG MUTUAL", merchant="Big Mutual", category="insurance")
    ins = row(sp.month_view(db, TODAY, OCT), "insurance")
    assert (ins["expected"], ins["expected_cents"], ins["state"], ins["tone"], ins["usual_cents"]) == (
        False, None, "as_usual", "check", 36_000)                                 # paid, it shows its amount only
    paid(db, chk, "insurance", "Big Mutual", (9,), 36_000)                        # now 4 of 6
    db.delete(db.scalar(select(Transaction).where(Transaction.posted_at == date(2026, 10, 9))))
    db.commit()
    assert row(sp.month_view(db, TODAY, OCT), "insurance")["state"] == "late"


def test_over_and_a_new_payee_stack_on_a_bill_but_a_commitment_never_warns(db):
    chk = make_account(db, "Checking")
    paid(db, chk, "subscriptions", "Streamflix", WINDOW, 12_000, day=3)
    paid(db, chk, "giving", "Grace Community", WINDOW, 14_000, day=3)
    make_txn(db, chk, date(2026, 10, 3), -12_000, "STREAMFLIX", merchant="Streamflix", category="subscriptions")
    make_txn(db, chk, date(2026, 10, 14), -4_000, "STREAMBOX", merchant="StreamBox", category="subscriptions")
    make_txn(db, chk, date(2026, 10, 3), -30_000, "GRACE COMMUNITY", merchant="Grace Community", category="giving")
    make_txn(db, chk, date(2026, 10, 4), -5_000, "FOOD BANK", merchant="Food bank", category="giving")
    v = sp.month_view(db, TODAY, OCT)
    subs, giving = row(v, "subscriptions"), row(v, "giving")
    assert (subs["state"], subs["tone"], subs["new_payee"]) == ("over", "amber", {"name": "StreamBox", "cents": 4_000})
    assert (giving["state"], giving["tone"], giving["new_payee"]) == ("over", "check", None)
    assert (v["head"]["fixed_summary"], v["head"]["fixed_more_cents"]) == ("more", 4_000)   # Bills only


def test_the_head_more_counts_bills_over_the_threshold_only(db):
    chk = make_account(db, "Checking")
    paid(db, chk, "utilities", "City Power", WINDOW, 41_000, day=2)
    paid(db, chk, "housing", "Home loan", WINDOW, 268_000, day=1)
    make_txn(db, chk, date(2026, 10, 1), -268_000, "HOME LOAN", merchant="Home loan", category="housing")
    make_txn(db, chk, date(2026, 10, 2), -43_000, "CITY POWER", merchant="City Power", category="utilities")   # $20 more
    h = sp.month_view(db, TODAY, OCT)["head"]
    assert (h["fixed_summary"], h["fixed_more_cents"], h["fixed_spent_cents"]) == ("plain", 0, 311_000)


def test_a_set_amount_stands_in_for_usual(db):
    household(db)
    db.add(SpendingTarget(category="housing", kind="fixed", monthly_cents=200_000, updated_at=AT, updated_by=1))
    db.commit()
    v = sp.month_view(db, TODAY, SEP)
    assert (row(v, "housing")["state"], row(v, "housing")["usual_cents"]) == ("over", 200_000)
    assert (v["head"]["fixed_expected_cents"], v["head"]["fixed_summary"], v["head"]["fixed_more_cents"]) == (
        253_000, "more", 68_000)
    db.get(SpendingTarget, "housing").monthly_cents = 350_000
    db.commit()
    v = sp.month_view(db, TODAY, SEP)
    assert (row(v, "housing")["state"], v["head"]["fixed_expected_cents"], v["head"]["fixed_summary"]) == (
        "under", 403_000, "plain")


def test_raw_text_and_old_rows_without_merchants_are_never_new(db):
    card = household(db)["card"]
    make_txn(db, card, date(2026, 9, 17), -799, "APPLE.COM/BILL 866-712-7753", category="subscriptions")
    subs = row(sp.month_view(db, TODAY, SEP), "subscriptions")
    assert (subs["spent_cents"], subs["state"], subs["merchant"], subs["new_payee"]) == (12_799, "as_usual", "Streamflix", None)
    first = row(sp.month_view(db, TODAY, date(2026, 4, 1)), "subscriptions")
    assert (first["state"], first["new_payee"]) == ("as_usual", None)              # the first month has nothing before it


def test_a_payment_and_a_bigger_credit_is_paid_and_reads_so_far(db):
    chk = household(db)["checking"]
    make_txn(db, chk, date(2026, 10, 12), -41_000, "CITY POWER", merchant="City Power", category="utilities")
    make_txn(db, chk, date(2026, 10, 13), 50_000, "CITY POWER CREDIT", merchant="City Power", category="utilities")
    v = sp.month_view(db, TODAY, OCT)
    u = row(v, "utilities")
    assert (u["state"], u["spent_cents"], u["refunds_cents"], u["came_out_on"], u["merchant"]) == (
        "so_far", 0, 50_000, "2026-10-12", "City Power")
    assert v["head"]["fixed_not_yet"] == 0


def test_an_unexpected_commitment_paid_shows_its_amount_last(db):
    chk = household(db)["checking"]
    make_txn(db, chk, date(2026, 5, 4), -3_000, "RED CROSS", merchant="Red Cross", category="giving")
    make_txn(db, chk, date(2026, 9, 4), -50_000, "FOOD BANK", merchant="Food bank", category="giving")
    v = sp.month_view(db, TODAY, SEP)
    assert v["fixed"][-1] == {
        "category": "giving", "kind": "commitment", "expected": False, "expected_cents": None, "usual_cents": 27_000,
        "spent_cents": 50_000, "refunds_cents": 0, "state": "as_usual", "tone": "check", "came_out_on": "2026-09-04",
        "merchant": "Food bank", "typical_day": 4, "new_payee": None, "outside_cents": 0}
    h = v["head"]
    assert (h["fixed_spent_cents"], h["fixed_expected_cents"], h["fixed_summary"]) == (371_000, 321_000, "plain")


def test_a_saved_kids_target_stays_flexible(db):
    chk = make_account(db, "Checking")
    paid(db, chk, "kids", "Toy Barn", WINDOW, 20_000)
    assert sp.settings(db)["kids"] == sp.Setting("commitment", None)                # no row: the new default
    db.add(SpendingTarget(category="kids", kind="everyday", monthly_cents=25_000, updated_at=AT, updated_by=1))
    db.commit()
    v = sp.month_view(db, TODAY, OCT)
    assert [r["category"] for r in v["everyday"]] == ["kids"] and v["fixed"] == []


def test_giving_outside_these_accounts_shows_on_givings_row_and_never_in_money_out(db):
    chk = make_account(db, "Checking")
    paid(db, chk, "giving", "Grace Community", (*WINDOW, 10), 14_000, day=3)
    before = sp.month_view(db, TODAY, OCT)
    add_fact(db, "giving.outside_cents", "5000", as_of=date(2026, 10, 20))
    after = sp.month_view(db, TODAY, OCT)
    assert (row(before, "giving")["outside_cents"], row(after, "giving")["outside_cents"]) == (0, 5_000)
    assert after["head"] == before["head"]
    assert row(after, "giving")["usual_cents"] == row(before, "giving")["usual_cents"] == 14_000
    add_fact(db, "giving.outside_cents", "0", as_of=date(2026, 10, 21))           # $0 clears it
    assert row(sp.month_view(db, TODAY, OCT), "giving")["outside_cents"] == 0


@pytest.fixture
def oct25(monkeypatch):
    monkeypatch.setattr("steward.clock.now", lambda: OCT_25)


def test_the_kind_route_saves_at_once_with_undo(oct25, signed_in, db):
    r = signed_in.put("/api/b/ours/spending/kinds/giving", json={"kind": "fixed"})
    assert r.status_code == 200
    body = r.json()
    assert (body["category"], body["kind"]) == ("giving", "fixed") and body["undo"]
    db.commit()                                                                  # ends the read snapshot
    assert sp.settings(db)["giving"] == sp.Setting("fixed", None)
    assert [e.message for e in db.scalars(select(EventLog).where(EventLog.kind == "spending"))] == [
        "JR changed Spending: Giving commitment → bill."]
    assert signed_in.post(f"/api/b/ours/undo/{body['undo']}").status_code == 200
    db.commit()                                                                  # ends the read snapshot
    assert db.get(SpendingTarget, "giving") is None                                 # the made row is gone


def test_the_kind_route_keeps_an_amount_except_for_once_in_a_while(oct25, signed_in, db):
    db.add(SpendingTarget(category="dining", kind="everyday", monthly_cents=50_000, updated_at=AT, updated_by=1))
    db.commit()
    assert signed_in.put("/api/b/ours/spending/kinds/dining", json={"kind": "fixed"}).status_code == 200
    db.commit()                                                                  # ends the read snapshot
    assert sp.settings(db)["dining"] == sp.Setting("fixed", 50_000)
    assert signed_in.put("/api/b/ours/spending/kinds/dining", json={"kind": "occasional"}).status_code == 200
    db.commit()                                                                  # ends the read snapshot
    assert sp.settings(db)["dining"] == sp.Setting("occasional", None)


def test_the_kind_route_refuses_in_plain_words(oct25, signed_in, db):
    r = signed_in.put("/api/b/ours/spending/kinds/giving", json={"kind": "weekly"})
    assert r.status_code == 422 and r.json() == {"error": "Choose Bill, Commitment, Flexible or Once in a while."}
    r = signed_in.put("/api/b/ours/spending/kinds/income", json={"kind": "fixed"})
    assert r.status_code == 404 and r.json() == {"error": "That isn't a category Spending tracks."}
