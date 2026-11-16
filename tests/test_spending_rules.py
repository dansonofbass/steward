"""Phase 11b's counting rules (spec, "What counts as spending", "The typical month", "Pace and states"), pinned at
their edges."""
from datetime import date, datetime, timezone

from steward.db.models import CATEGORIES, SPENDING_KINDS, SpendingTarget
from steward.services import spending as sp
from tests.factories import make_account, make_txn

TODAY = date(2026, 10, 25)
AT = datetime(2026, 10, 1, 17, 0, tzinfo=timezone.utc)
OCT = (date(2026, 10, 1), date(2026, 11, 1))


def test_every_category_has_one_kind_or_is_never_spending():
    assert sp.KINDS is SPENDING_KINDS
    assert sp.SPENDING_CATEGORIES == tuple(c for c in CATEGORIES if c not in (
        "income", "business_income", "interest", "transfer", "investment", "reimbursement", "uncategorized"))
    assert len(sp.SPENDING_CATEGORIES) == 23
    assert {c for c, k in sp.DEFAULT_KINDS.items() if k == "fixed"} == {
        "housing", "utilities", "insurance", "loan_payments", "subscriptions"}
    assert {c for c, k in sp.DEFAULT_KINDS.items() if k == "commitment"} == {"giving", "childcare_education", "kids"}
    assert {c for c, k in sp.DEFAULT_KINDS.items() if k == "occasional"} == {"taxes"}
    assert sp.DEFAULT_KINDS["fees"] == sp.DEFAULT_KINDS["business_expense"] == "everyday"
    assert set(sp.LABELS) == set(sp.SPENDING_CATEGORIES) and sp.LABELS["dining"] == "Eating out"


def test_transfers_never_count_and_refunds_net_against_their_category(db):
    chk = make_account(db, "Checking")
    card = make_account(db, "Card", type="credit")
    k401 = make_account(db, "401(k)", type="k401", owner="jr")
    d = date(2026, 10, 5)
    make_txn(db, chk, d, -10_000, "DINER", category="dining")
    make_txn(db, card, d, 6_000, "DINER REFUND", category="dining")
    make_txn(db, chk, d, -50_000, "PAYMENT TO CARD", category="transfer")               # the feed didn't pair it
    make_txn(db, chk, d, -20_000, "TO SAVINGS", category="transfer", is_transfer=True)
    make_txn(db, chk, d, -30_000, "TO SAVINGS", category="shopping", is_transfer=True)  # paired, whatever its category
    make_txn(db, k401, d, -3_000, "PLAN FEE", category="fees")                          # not a cash account
    make_txn(db, chk, d, -2_500, "SQ *VENDOR", category="uncategorized")
    make_txn(db, chk, d, -1_500, "POS DEBIT", category="uncategorized")
    make_txn(db, chk, d, 800, "MYSTERY CREDIT", category="uncategorized")
    m = sp.category_months(db, *OCT)["2026-10"]
    assert m["dining"] == sp.Flow(in_cents=6_000, out_cents=10_000, out_rows=1)
    assert sp.spent(m["dining"]) == 4_000
    assert m["uncategorized"] == sp.Flow(in_cents=800, out_cents=4_000, out_rows=2)
    assert set(m) == {"dining", "uncategorized"}


def test_a_business_split_counts_only_its_personal_share(db):
    chk = make_account(db, "Checking")
    biz = make_account(db, "Business checking", type="business_checking", owner="business")
    d = date(2026, 10, 6)
    make_txn(db, chk, d, -10_000, "MOBILE ONE WIRELESS", category="utilities", business_pct=40)   # $60 is personal
    make_txn(db, chk, d, -1_001, "HALF CAFE", category="dining", business_pct=50)                # 1,001 less its 501
    make_txn(db, biz, d, -9_000, "TEAM LUNCH", category="dining", business_pct=0)                # personal, on a business account
    make_txn(db, biz, d, -7_000, "CLOUDHOST", category="business_expense")                      # business by account
    make_txn(db, chk, d, -5_000, "ALL BUSINESS", category="dining", is_business=True)
    m = sp.category_months(db, *OCT)["2026-10"]
    assert m["utilities"] == sp.Flow(0, 6_000, 1)
    assert m["dining"] == sp.Flow(0, 500 + 9_000, 2)
    assert "business_expense" not in m


def test_refunds_bigger_than_spending_show_nothing_spent_never_less(db):
    chk = make_account(db)
    make_txn(db, chk, date(2026, 9, 3), -4_000, "SHOE STORE", category="shopping")
    make_txn(db, chk, date(2026, 9, 9), 10_000, "SHOE STORE RETURN", category="shopping")
    m = sp.category_months(db, date(2026, 9, 1), date(2026, 10, 1))["2026-09"]
    assert sp.spent(m["shopping"]) == 0
    assert sp.spent(None) == 0 and sp.received(None) == 0
    assert sp.received(sp.Flow(10_000, 4_000, 1)) == 6_000


def test_the_typical_month_is_the_median_rounded_to_ten_dollars_half_up():
    assert sp.typical_cents([41_000, 62_000, 38_000, 44_000, 47_000, 51_000]) == 46_000   # median $455 → $460
    assert sp.typical_cents([12_340]) == 12_000
    assert sp.typical_cents([1_499]) == 1_000 and sp.typical_cents([1_500]) == 2_000
    assert sp.typical_cents([0, 0, 0]) == 0
    assert sp.typical_cents([]) is None


def test_the_typical_months_are_the_last_six_complete_ones(db):
    chk = make_account(db)
    for m in range(1, 11):                                   # January to October 2026
        make_txn(db, chk, date(2026, m, 1), -100, "A", category="dining")
    assert sp.window_sums(db, TODAY)[0] == ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
    assert sp.earliest_month(db) == "2026-01"


def test_a_month_without_data_is_skipped_and_an_older_one_taken(db):
    chk = make_account(db)
    for m in range(1, 11):                                   # January to October 2026
        if m != 6:                                           # June has nothing at all
            make_txn(db, chk, date(2026, m, 1), -100, "A", category="dining")
    make_txn(db, chk, date(2026, 6, 4), -50_000, "PAYMENT TO CARD", category="transfer")   # not counted: no data
    assert sp.window_sums(db, TODAY)[0] == ["2026-03", "2026-04", "2026-05", "2026-07", "2026-08", "2026-09"]
    window, sums = sp.window_sums(db, TODAY)
    assert set(sums) == set(window)


def test_fewer_months_only_when_history_runs_out(db):
    chk = make_account(db)
    for m in (5, 7, 9):                                      # May, July and September, gaps between
        make_txn(db, chk, date(2026, m, 1), -100, "A", category="dining")
    assert sp.window_sums(db, TODAY)[0] == ["2026-05", "2026-07", "2026-09"]


def test_a_book_that_starts_mid_month_leaves_that_month_out(db):
    chk = make_account(db)
    make_txn(db, chk, date(2026, 8, 14), -100, "A", category="dining")
    make_txn(db, chk, date(2026, 9, 2), -100, "A", category="dining")
    assert sp.window_sums(db, TODAY)[0] == ["2026-09"]


def test_the_book_starts_at_its_first_row_even_a_transfer(db):
    # The book's start is vault_flows.counted_start's (every personal row); only which months have data and their
    # sums leave transfer-category rows out.
    chk = make_account(db)
    make_txn(db, chk, date(2026, 8, 14), -50_000, "PAYMENT TO CARD", category="transfer")
    make_txn(db, chk, date(2026, 9, 2), -100, "A", category="dining")
    assert sp.window_sums(db, TODAY)[0] == ["2026-09"]


def test_a_transfer_on_the_first_makes_that_month_complete(db):
    chk = make_account(db)
    make_txn(db, chk, date(2026, 8, 1), -50_000, "PAYMENT TO CARD", category="transfer")
    make_txn(db, chk, date(2026, 8, 3), -100, "A", category="dining")
    make_txn(db, chk, date(2026, 9, 2), -100, "A", category="dining")
    assert sp.window_sums(db, TODAY)[0] == ["2026-08", "2026-09"]


def test_a_new_book_has_no_typical_months(db):
    assert sp.window_sums(db, TODAY)[0] == [] and sp.earliest_month(db) is None
    chk = make_account(db)
    make_txn(db, chk, date(2026, 10, 2), -100, "A", category="dining")   # this month never counts
    window, sums = sp.window_sums(db, TODAY)
    assert window == [] and sp.typicals(window, sums)["dining"] is None
    assert sp.typical_income(window, sums) is None


def test_a_month_without_the_category_counts_as_nothing(db):
    chk = make_account(db)
    for m in range(4, 10):
        make_txn(db, chk, date(2026, m, 1), -268_000, "HOMELOAN", category="housing")
        make_txn(db, chk, date(2026, m, 1), 512_000, "PAYROLL", category="income")
    make_txn(db, chk, date(2026, 8, 3), -40_000, "AIRLINE", category="travel")
    make_txn(db, chk, date(2026, 9, 3), -60_000, "HOTEL", category="travel")
    window, sums = sp.window_sums(db, TODAY)
    t = sp.typicals(window, sums)
    assert (t["housing"], t["travel"], t["gifts"]) == (268_000, 0, 0)
    assert sp.typical_income(window, sums) == 512_000


def test_pace_is_over_or_on_track_by_the_over_level():
    # $500 target, day 25 of 31: usual by today is 50,000 × 25 / 31 = 40,322.6 → 40,323 (the bar's today mark)
    assert sp.pace(46_800, 50_000, 25, 31) == ("on_track", 40_323)     # ahead of pace is not a state any more (P17)
    assert sp.pace(50_499, 50_000, 25, 31) == ("on_track", 40_323)     # over by less than $5 is on target
    assert sp.pace(50_500, 50_000, 25, 31) == ("over", 40_323)
    assert sp.pace(50_500, 50_000, 7, 31) == ("on_track", 11_290)      # days 1-7: a little over is on target
    assert sp.pace(60_000, 50_000, 7, 31)[0] == "over"                 # clearly over shows from day 1
    assert sp.pace(49_000, 50_000, None, 30) == ("on_track", None)
    assert sp.pace(50_600, 50_000, None, 30) == ("over", None)          # a closed month skips the days 1-7 rule
    assert sp.pace(9_000, None, 25, 31) == ("none", None)
    assert sp.pace(500, 0, 25, 31) == ("over", 0) and sp.pace(499, 0, 25, 31) == ("on_track", 0)


def test_everyday_order_is_by_target_then_typical_month_then_the_list():
    rows = [("gifts", None, 6_000), ("dining", 50_000, 47_000), ("groceries", 130_000, 124_000),
            ("personal", None, 9_000), ("shopping", 50_000, 39_000), ("travel", None, None), ("kids", None, 0)]
    assert sp.everyday_order(rows) == ["groceries", "dining", "shopping", "personal", "gifts", "kids", "travel"]


def test_settings_fill_in_default_kinds_and_a_saved_row_wins(db):
    assert sp.has_targets(db) is False
    db.add(SpendingTarget(category="taxes", kind="everyday", monthly_cents=None, updated_at=AT, updated_by=1))
    db.commit()
    assert sp.has_targets(db) is False                                     # a kind alone is not a target
    db.add(SpendingTarget(category="subscriptions", kind="everyday", monthly_cents=12_000, updated_at=AT, updated_by=1))
    db.commit()
    s = sp.settings(db)
    assert set(s) == set(sp.SPENDING_CATEGORIES)
    assert s["subscriptions"] == sp.Setting("everyday", 12_000)
    assert s["taxes"] == sp.Setting("everyday", None)
    assert s["housing"] == sp.Setting("fixed", None) and s["insurance"] == sp.Setting("fixed", None)
    assert sp.has_targets(db) is True
