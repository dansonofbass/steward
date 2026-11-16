"""Suggestions (spec, Suggestions; decision 5): yearly from 10-14 month gaps over 2 or more payments, twice a year
from 5-7 month gaps, one county tax payment as twice a year, too little history, dismissed and brought back."""
from datetime import date

from steward.db.models import SetAside
from steward.services import setasides as sa
from tests.factories import make_account, make_txn
from tests.setaside_fixtures import AT, FIRST, TODAY, household


def pay(db, acct, d, cents, raw, merchant, category):
    return make_txn(db, acct, d, -cents, raw, merchant=merchant, category=category)


def big_mutual(db, chk):
    pay(db, chk, date(2025, 5, 9), 132_000, "BIG MUTUAL INS", "Big Mutual", "insurance")
    pay(db, chk, date(2026, 5, 12), 138_000, "BIG MUTUAL INS", "Big Mutual", "insurance")


def test_yearly_twice_a_year_and_one_county_payment(db):
    chk = make_account(db, "Checking")
    for i in range(14):                                     # 14 months of groceries: history enough
        m = 9 + i - 1
        make_txn(db, chk, date(2025 + m // 12, m % 12 + 1, 1), -10_000, "GROCER", category="groceries")
    big_mutual(db, chk)
    for d in (date(2025, 1, 15), date(2025, 7, 15), date(2026, 1, 15), date(2026, 7, 15)):
        pay(db, chk, d, 45_000, "MAPLE COURT HOA", "Maple Court HOA", "housing")
    pay(db, chk, date(2026, 4, 10), 421_000, "COUNTY TAX COLLECTOR", "County Tax Collector", "taxes")
    pay(db, chk, date(2026, 3, 3), 41_200, "DMV RENEWAL", "DMV", "transport")          # once: not suggested
    pay(db, chk, date(2026, 2, 1), 9_000, "GYMTIME", "Gymtime", "personal")             # monthly: not suggested
    pay(db, chk, date(2026, 3, 1), 9_000, "GYMTIME", "Gymtime", "personal")
    pay(db, chk, date(2026, 4, 1), 9_000, "GYMTIME", "Gymtime", "personal")
    got = sa.find_occasional(db, TODAY)
    assert [(s["name"], s["group"], s["kind"], s["amount_cents"], s["monthly_cents"]) for s in got] == [
        ("Property tax", "home", "twice_yearly", 421_000, 70_167),
        ("Big Mutual", "other", "yearly", 138_000, 11_500),
        ("Maple Court HOA", "other", "twice_yearly", 45_000, 7_500)]
    county, mutual, hoa = got
    assert (county["due_month"], county["due_day"], county["second_month"], county["second_day"]) == (4, 10, 10, 10)
    assert (mutual["due_month"], mutual["due_day"], mutual["payments"]) == (5, 12, ["2026-05-12", "2025-05-09"])
    assert (hoa["due_month"], hoa["due_day"], hoa["second_month"], hoa["second_day"]) == (7, 15, 1, 15)
    assert hoa["payee_key"] == "MAPLE COURT HOA" and mutual["category"] == "insurance"
    assert (county["months"], mutual["months"], hoa["months"]) == ([4, 10], [5], [1, 7])
    assert (county["yearly_cents"], mutual["yearly_cents"], hoa["yearly_cents"]) == (842_000, 138_000, 90_000)
    assert not {"basis", "county", "payee_name"} & set(county)


def test_three_years_running_and_an_uneven_gap(db):
    chk = make_account(db, "Checking")
    for d in (date(2024, 10, 1), date(2025, 9, 20), date(2026, 10, 2)):
        pay(db, chk, d, 50_000, "CLUB MEMBERSHIP", "The Club", "personal")             # 11 and 13 months: yearly
    for d in (date(2025, 1, 10), date(2025, 10, 10), date(2026, 10, 10)):
        pay(db, chk, d, 50_000, "ODD SHOP", "Odd Shop", "home")                        # 9 and 12 months: no
    got = {s["name"]: s for s in sa.find_occasional(db, TODAY)}
    assert set(got) == {"The Club"} and got["The Club"]["group"] == "memberships"
    assert got["The Club"]["payments"] == ["2026-10-02", "2025-09-20", "2024-10-01"]


def test_what_is_left_out_and_dismissed(db):
    h = household(db)
    chk = h["accounts"]["checking"]
    big_mutual(db, chk)
    pay(db, chk, date(2025, 8, 14), 180_000, "SAFEGUARD INSURANCE", "Safeguard Insurance", "insurance")
    pay(db, chk, date(2026, 8, 14), 186_000, "SAFEGUARD INSURANCE", "Safeguard Insurance", "insurance")
    names = lambda: [s["name"] for s in sa.find_occasional(db, TODAY)]   # noqa: E731
    assert names() == ["Big Mutual"]                                          # County and Safeguard are covered by set-asides
    sa.dismiss(db, "BIG MUTUAL", "insurance", by=1)
    db.commit()
    assert names() == []
    v = sa.suggestions_view(db, TODAY)
    assert v["suggestions"] == [] and [(d["payee_name"], d["monthly_cents"]) for d in v["dismissed"]] == [("Big Mutual", 11_500)]
    assert sa.restore(db, "BIG MUTUAL", "insurance") is True and sa.restore(db, "BIG MUTUAL", "insurance") is False
    db.commit()
    assert names() == ["Big Mutual"]


def test_a_refusal_alone_keeps_a_payee_out(db):
    chk = make_account(db, "Checking")
    big_mutual(db, chk)
    assert [s["name"] for s in sa.find_occasional(db, TODAY)] == ["Big Mutual"]
    bm = SetAside(name="Temp", kind="yearly", amount_cents=138_000, due_month=5, due_day=12, first_month=FIRST,
                  payee_key="BIG MUTUAL", category="insurance", created_at=AT, updated_at=AT)
    db.add(bm)
    db.commit()
    m = sa.match_set_aside(db, bm, TODAY)[0]
    sa.refuse(db, m.transaction_id, by=1)
    # The set-aside now covers someone else, so only the refusal is left. (A set-aside is never deleted, only archived,
    # and its refusals point at it: deleting it here broke the foreign key the book enforces.)
    bm.payee_key = "SOMEONE ELSE"
    db.commit()
    assert sa.find_occasional(db, TODAY) == []


def test_a_set_aside_with_a_payee_covers_it_whatever_the_category_and_archived_ones_still_cover(db):
    chk = make_account(db, "Checking")
    big_mutual(db, chk)
    assert len(sa.find_occasional(db, TODAY)) == 1
    s = SetAside(name="Mutual", kind="yearly", amount_cents=138_000, due_month=5, due_day=12, first_month=FIRST,
                 payee_key="BIG MUTUAL", created_at=AT, updated_at=AT)       # no category
    db.add(s)
    db.commit()
    assert sa.find_occasional(db, TODAY) == []
    s.archived_at = AT
    db.commit()
    assert sa.find_occasional(db, TODAY) == []                                  # stopping it does not bring it back


def test_a_set_aside_with_only_a_category_covers_the_category(db):
    chk = make_account(db, "Checking")
    big_mutual(db, chk)
    pay(db, chk, date(2025, 3, 9), 50_000, "CLUB MEMBERSHIP", "The Club", "personal")
    pay(db, chk, date(2026, 3, 9), 50_000, "CLUB MEMBERSHIP", "The Club", "personal")
    db.add(SetAside(name="Insurance", kind="yearly", amount_cents=138_000, due_month=5, due_day=12, first_month=FIRST,
                    category="insurance", created_at=AT, updated_at=AT))
    db.commit()
    assert [s["name"] for s in sa.find_occasional(db, TODAY)] == ["The Club"]


def test_too_little_history_says_so(db):
    chk = make_account(db, "Checking")
    assert sa.history_months(db, TODAY) == 0
    make_txn(db, chk, date(2026, 7, 14), -10_000, "GROCER", category="groceries")
    make_txn(db, chk, date(2026, 10, 1), -10_000, "GROCER", category="groceries")
    assert sa.history_months(db, TODAY) == 3                       # July 14 to Oct 25 is 103 days
    v = sa.suggestions_view(db, TODAY)
    assert v["history_months"] == 3 and v["suggestions"] == []
    for i in range(40):
        make_txn(db, chk, date(2022 + i // 12, i % 12 + 1, 1), -10_000, "GROCER", category="groceries")
    assert sa.history_months(db, TODAY) == 25                      # capped at the 25 months looked at


def test_the_window_is_25_months(db):
    chk = make_account(db, "Checking")
    pay(db, chk, date(2024, 8, 20), 50_000, "CLUB MEMBERSHIP", "The Club", "personal")      # before Sep 1, 2024 (25 months back): out
    pay(db, chk, date(2025, 8, 20), 50_000, "CLUB MEMBERSHIP", "The Club", "personal")
    assert sa.find_occasional(db, TODAY) == []                                       # one payment inside the window is not enough
    pay(db, chk, date(2026, 8, 20), 50_000, "CLUB MEMBERSHIP", "The Club", "personal")
    assert [s["kind"] for s in sa.find_occasional(db, TODAY)] == ["yearly"]


def test_several_irregular_county_payments_are_twice_a_year_and_the_negatives(db):
    chk = make_account(db, "Checking")
    for d, c in ((date(2025, 10, 10), 400_000), (date(2026, 1, 10), 410_000), (date(2026, 10, 10), 421_000)):   # gaps 3 and 9
        pay(db, chk, d, c, "COUNTY TAX COLLECTOR", "County Tax Collector", "taxes")
    for d in (date(2025, 10, 10), date(2026, 1, 10), date(2026, 10, 10)):
        pay(db, chk, d, 30_000, "COUNTY PARKS FEE", "County Parks", "recreation")      # county, not Taxes
        pay(db, chk, d, 30_000, "STATE REVENUE", "State Revenue", "taxes")             # Taxes, not county
    got = sa.find_occasional(db, TODAY)
    assert [(s["name"], s["kind"], s["amount_cents"]) for s in got] == [("Property tax", "twice_yearly", 421_000)]
    s = got[0]
    assert (s["due_month"], s["due_day"], s["second_month"], s["second_day"]) == (10, 10, 4, 10)


def test_a_dismissed_payee_that_is_now_set_aside_leaves_the_folded_list(db):
    chk = make_account(db, "Checking")
    big_mutual(db, chk)
    sa.dismiss(db, "BIG MUTUAL", "insurance", by=1)
    db.commit()
    assert [d["payee_name"] for d in sa.dismissed_view(db, TODAY)] == ["Big Mutual"]
    db.add(SetAside(name="Mutual", kind="yearly", amount_cents=138_000, due_month=5, due_day=12, first_month=FIRST,
                    payee_key="BIG MUTUAL", category="insurance", created_at=AT, updated_at=AT))
    db.commit()
    assert sa.dismissed_view(db, TODAY) == []


def test_history_months_is_days_over_30_44(db):
    chk = make_account(db, "Checking")
    assert sa.history_months(db, TODAY) == 0
    make_txn(db, chk, date(2026, 7, 27), -10_000, "GROCER", category="groceries")        # 90 days before Oct 25
    assert (TODAY - date(2026, 7, 27)).days == 90 and sa.history_months(db, TODAY) == 3
    make_txn(db, chk, date(2020, 1, 1), -10_000, "GROCER", category="groceries")
    assert sa.history_months(db, TODAY) == 25
